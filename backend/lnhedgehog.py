from ast import parse
from locale import currency
from os import get_inheritable
from random import seed
import re
from kollider_api_client.ws import KolliderWsClient
from kollider_api_client.rest import KolliderRestClient
from utils import *
from lnd_client import LndClient
from kollider_msgs import OpenOrder, Position, TradableSymbol, Ticker, Orderbook
from time import sleep
from threading import Lock
import json
from math import floor
import uuid
from pprint import pprint
import threading
from custom_errors import *
from classes import *
from constants import *
import requests
from lnurl_auth import perform_lnurlauth
import lnurl

import zmq
import copy
import os

SOCKET_PUB_ADDRESS = "tcp://*:5559"
SOCKET_SUB_ADDRESS = os.environ.get('ZONIC_ZMQ_SUB_ADDRESS')

SEED_WORD = hashlib.sha256("cheers to you until all enternity and here is my entry ser. thi is for zonic.".encode("utf-8")).digest()

def save_to_settings(settings):
    with open(settings["settings_path"], 'w') as outfile:
        json.dump(settings, outfile, indent=4, sort_keys=True)

class HedgerEngine(KolliderWsClient):
    def __init__(self, lnd_client, logger):
        self.kollider_api_key = None
        self.kollider_api_secret = None
        self.kollider_api_passphrase = None
        # Positions that are currently open on the Kollider platform.
        self.positions = {}
        self.current_index_price = 0
        self.current_mark_price = 0
        self.target_fiat_currency = "USD"
        self.target_symbol = "BTCUSD.PERP"
        self.target_index_symbol = ".BTCUSD"
        self.orderbook = None
        self.ws_is_open = False
        self.contracts = {}

        self.is_kollider_authenticated = False
        self.kollider_withdrawal_state = KolliderWithdrawalState()

        self.hedge_value = 0

        self.target_leverage = 100
        self.target_dollar_amount = 0

        # Last hedge state.
        self.last_state = HedgerState()

        # Summary of the connected node.
        self.node_info = None

        # Order type that is used to make trades on Kollider.
        self.order_type = "Market"

        self.master_wallet = MasterWallet()

        self.synth_wallets = {}
        for symbol in AVAILABLE_CURRENCIES:
            wallet = SynthWallet(symbol)
            wallet.setDenomination(CURRENCY_DENOMINATION_MAP[symbol])
            wallet.setDp(CURRENCY_DP_MAP[CURRENCY_DENOMINATION_MAP[symbol]])
            self.synth_wallets[symbol] = wallet

        self.lnd_client = lnd_client

        self.last_ticker = Ticker()

        self.received_tradable_symbols = False

        context = zmq.Context()
        self.publisher = context.socket(zmq.PUB)
        self.publisher.bind(SOCKET_PUB_ADDRESS)

        self.settings = {}
        self.logger = logger

    def has_kollider_creds(self):
        return self.kollider_api_key and self.kollider_api_secret and self.kollider_api_passphrase

    def to_dict(self):
        return {
            "node_info": self.node_info,
            "wallet": self.master_wallet.to_dict(),
            "current_index_price": self.current_index_price,
            "current_mark_price": self.current_mark_price,
            "last_state": self.last_state.to_dict(),
            "target_fiat_currency": self.target_fiat_currency,
            "target_symbol": self.target_index_symbol,
            "target_index_symbol": self.target_index_symbol,
            "hedge_value": self.hedge_value,
            "staged_hedge_value": self.staged_hedge_value,
        }

    def set_params(self, **args):
        pprint(args)
        self.target_dollar_amount = args.get(
            "target_dollar_amount") if args.get("target_dollar_amount") else 0
        self.target_fiat_currency = args.get(
            "target_fiat_currency") if args.get("target_fiat_currency") else None
        self.target_symbol = args.get(
            "target_symbol") if args.get("target_symbol") else None
        self.target_index_price = args.get("target_index_symbol") if args.get(
            "target_index_symbol") else None
        self.target_leverage = args.get(
            "target_leverage") if args.get("target_leverage") else None
        self.order_type = args.get("order_type") if args.get(
            "order_type") else "Market"

    def publish_msg(self, msg, type):
        message = {
            "type": type,
            "data": msg,
        }
        self.publisher.send_multipart(["hedger_sub_stream".encode("utf-8"), json.dumps([message]).encode("utf-8")])

    def on_open(self, event):
        self.jwt_auth()
        sleep(1)
        self.sub_index_price([self.target_index_symbol])
        self.sub_mark_price([self.target_symbol])
        self.sub_ticker([self.target_symbol])
        self.sub_position_states()
        self.sub_orderbook_l2(self.target_symbol)
        self.fetch_positions()
        self.fetch_open_orders()
        self.fetch_tradable_symbols()
        self.fetch_ticker(self.target_symbol)
        self.fetch_balances()
        self.ws_is_open = True

    def on_pong(self, ctx, event):
        None

    def on_error(self, ctx, event):
        pass

    def on_message(self, _ctx, msg):
        msg = json.loads(msg)
        t = msg["type"]
        data = msg["data"]
        # self.logger.debug("Received Kollider msg type: {}".format(t))
        # self.logger.debug("Received Kollider data: {}".format(data))
        if t == 'authenticate':
            if data["message"] == "success":
                self.is_kollider_authenticated = True
                self.who_am_i()
                self.update_wallet_data()
            else:
                self.logger.info("Kollider auth Unsuccessful: {}".format(data))
                self.is_kollider_authenticated = False
                self.__reset()

        elif t == 'whoami':
            print(data)

        elif t == 'index_values':
            self.current_index_price = float(data["value"])

        elif t == 'mark_prices':
            self.current_mark_price = float(data["price"])

        elif t == 'positions':
            positions = data["positions"]
            for key, value in positions.items():
                self.positions[key] = Position(msg=value)
            self.publish_synth_wallets()

        elif t == 'tradable_symbols':
            for symbol, contract in data["symbols"].items():
                self.contracts[symbol] = TradableSymbol(msg=contract)
            self.received_tradable_symbols = True

        elif t == 'fill':
            msg = {
                "orderId": data["order_id"]
            }
            self.publish_msg(msg, "fill")

        elif t == 'position_states':
            position = Position(msg=data)
            if position.symbol == self.target_symbol:
                if position.quantity == 0:
                    del self.positions[self.target_symbol]
                else:
                    self.positions[self.target_symbol] = position

        elif t == 'ticker':
            self.last_ticker = Ticker(msg=data)

        elif t == 'order_invoice':
            res = self.lnd_client.send_payment(data["invoice"])

        elif t == 'settlement_request':
            amount = data["amount"]
            self.make_withdrawal(amount, "Kollider Trade Settlement")

        elif t == "level2state":
            if data["update_type"] == "snapshot":
                ob = copy.copy(Orderbook("kollider"))
                for key, value in data["bids"].items():
                    ob.bids[int(key)] = value

                for key, value in data["asks"].items():
                    ob.asks[int(key)] = value

                if self.orderbook is not None:
                    del self.state.orderbooks[data["symbol"]]
                self.orderbook = ob
            else:
                bids = data["bids"]
                asks = data["asks"]
                if not self.orderbook:
                    return
                if bids:
                    for price, quantity in bids.items():
                        if quantity == 0:
                            del self.orderbook.bids[int(price)]
                        else:
                            self.orderbook.bids[int(price)] = quantity
                if asks:
                    for price, quantity in asks.items():
                        if quantity == 0:
                            del self.orderbook.asks[int(price)]
                        else:
                            self.orderbook.asks[int(price)] = quantity

        elif t == 'balances':
            total_balance = 0
            cash_balance = float(data["cash"])
            isolated_margin = float(data["isolated_margin"].get(self.target_symbol))
            order_margin = float(data["order_margin"].get(self.target_symbol))
            if isolated_margin is not None:
                total_balance += float(isolated_margin)
                self.master_wallet.update_kollider_isolated_margin(isolated_margin)
            if order_margin is not None:
                total_balance += float(order_margin)
                self.master_wallet.update_kollider_cash(cash_balance)

        elif t == 'withdrawal_success':
            self.logger.debug("Withdrawal success received.")
            self.kollider_withdrawal_in_process = False

        elif t == 'error':
            self.logger.error("Got error: {}".format(msg))

    def hydrate_client(self):
        self.publish_synth_wallets()
        self.update_master_wallet()
        self.publish_synth_wallets()

    def publish_synth_wallets(self):
        self.update_wallet_data()
        for key, value in self.synth_wallets.items():
            self.publish_msg(value.to_dict(), "synthWallet")

    def calc_sat_value(self, qty, price, contract):
        if contract.is_inverse_priced:
            return 1 / price * qty * SATOSHI_MULTIPLIER
        else:
            return price * qty * SATOSHI_MULTIPLIER

    def calc_contract_value(self):
        if self.contracts.get(self.target_symbol) is not None:
            contract = self.get_contract()
            price = self.current_mark_price
            if price == 0:
                return 0
            if contract.is_inverse_priced:
                return contract.contract_size / price * SATOSHI_MULTIPLIER
            else:
                return contract.contract_size * price * SATOSHI_MULTIPLIER
        else:
            raise Exception("Target contract not available")

    def calc_average_price(self, qty_1, qty_2, price_1, price_2, contract):
        if contract.is_inverse_priced:
            return (qty_1 + qty_2) / (qty_1 / price_1 + qty_2 / price_2)
        return (qty_1 * price_1 + qty_2 * price_2) / (qty_1 + qty_2)

    def convert_price(self, price, contract):
        return price / 10 ** contract.price_dp

    def calc_average_entry(self, side, amount_in_sats):
        bucket = None
        if side == "bid":
            bucket = reversed(self.orderbook.bids.items())
        else:
            bucket = self.orderbook.asks.items()

        remaining_value = amount_in_sats

        contract = self.contracts.get(self.target_symbol)
        if not contract:
            return

        running_numerator = 0
        running_denominator = 0

        for (price, qty) in bucket:
            price = self.convert_price(price, contract)
            value = self.calc_sat_value(qty, price, contract)
            remaining_value -= value
            if contract.is_inverse_priced:
                running_numerator += qty
                running_denominator += qty / price
            else:
                running_numerator += qty * price
                running_denominator += qty
            if remaining_value <= 0:
                break

        if remaining_value <= 0:
            return running_numerator / running_denominator

        raise InsufficientBookDepth(remaining_value)

    def estimate_conversion(self, amount_in_dollar):
        position = self.positions.get(self.target_symbol)
        contract = self.contracts.get(self.target_symbol)
        conversion_est = ConversionEstimation()
        if not contract:
            conversion_est.error_reason = "ContractNotAvailable"
            conversion_est.is_error = True
            return conversion_est

        ## Contract value in Sats.
        contract_value = self.calc_contract_value()

        # User wants to convert Dollar into Bitcoin.
        if amount_in_dollar < 0:
            # Check user has enough contracts.
            if not position and amount_in_dollar < 0 or position.quantity < amount_in_dollar:
                print("User doesn't have enough balance.")
                conversion_est.error_reason = "InsufficientFunds"
                conversion_est.is_error = True
                return conversion_est

        # Cost is negative if person is selling dollars (contracts).
        cost_in_sats = abs(amount_in_dollar) * contract_value

        fill_price = 0
        ## User wants to buy contracts (Bitcoin) for dollars -> Ask Side.
        if amount_in_dollar < 0:
            ob = self.orderbook.asks.items()
            for key, _ in ob:
                fill_price = key
        else:
            ob = reversed(self.orderbook.bids.items())
            for key, _ in ob:
                fill_price = key
            
        conversion_est.usd_value = amount_in_dollar
        conversion_est.btc_value = abs(cost_in_sats)
        conversion_est.estimated_fill_price = fill_price
        conversion_est.fees = cost_in_sats * TAKER_FEE

        return conversion_est

    def make_conversion(self, amount_in_dollar):
        self.logger.debug("Trying to make conversion of {} USD".format(amount_in_dollar))
        new_target_dollar_amount = self.target_dollar_amount
        new_target_dollar_amount += amount_in_dollar
        self.logger.debug("New dollar target: {}".format(new_target_dollar_amount))
        if new_target_dollar_amount < 0:
            self.logger.error("Trying to have negative dollars.")
            msg = {
                "msg": "You cannot have less dollar than you own."
            }
            self.publish_msg(msg, "error")
            return
        self.target_dollar_amount = new_target_dollar_amount
        self.settings["target_dollar_amount"] = new_target_dollar_amount
        save_to_settings(self.settings)

    def make_withdrawal(self, amount, message):
        if self.kollider_withdrawal_state.in_progress:
            elapsed = time.time() - self.kollider_withdrawal_state.started
            self.logger.debug("Elapsed time from when withdrawal started: {}".format(elapsed))
            if elapsed > 30:
                self.logger.debug("Stale withdrawal state. Resetting...")
                self.kollider_withdrawal_state.finished()
            else:
                self.logger.debug("Withdrawal ongoing. Waiting to finish or to timeout.")
                return
        amt = int(amount)
        res = self.lnd_client.add_invoice(amt, message)
        withdrawal_request = {
            "withdrawal_request": {
                "Ln": {
                    "payment_request": res.payment_request,
                    "amount": amt,
                }
            }
        }
        self.withdrawal_request(withdrawal_request)
        self.kollider_withdrawal_state.set_in_progress()
        self.kollider_withdrawal_state.reset_time()

    def sweep_excess_funds_from_kollide(self):
        if self.master_wallet.kollider_cash > 1:
            self.make_withdrawal(self.master_wallet.kollider_cash, "Kollider withdrawal")

    def calc_number_of_contracts_required(self, value_target):
        try:
            value_per_contract = self.calc_contract_value()
            qty_of_contracts = floor(value_target / value_per_contract)
            return qty_of_contracts
        except Exception as e:
            self.logger.exception("Got exception on calc_number_of_contracts_required: {}".format(e))

    def get_open_position(self):
        return self.positions.get(self.target_symbol)

    def get_contract(self):
        return self.contracts.get(self.target_symbol)

    def get_best_price(self, side):
        if side == "Bid":
            return self.last_ticker.best_bid
        else:
            return self.last_ticker.best_ask

    def build_target_state(self):
        state = HedgerState()

        open_ask_order_quantity = 0
        open_bid_order_quantity = 0

        current_position_quantity = 0

        # Getting current position on target symbol.
        open_position = self.get_open_position()

        if open_position is not None:
            current_position_quantity = open_position.quantity

        state.target_quantity = self.target_dollar_amount
        state.target_value = self.calc_contract_value() * self.target_dollar_amount
        state.position_quantity = current_position_quantity

        self.last_state = state

        return state

    def converge_state(self, state):
        # Nothing needs to be done if target is current.

        current_qty = state.position_quantity
        target_qty = state.target_quantity

        self.logger.debug("Current Qty: {}".format(current_qty))
        self.logger.debug("Target Qty: {}".format(target_qty))

        if target_qty == current_qty:
            self.logger.debug("Target quantity is equalt to current quantity.")
            return

        contract = self.get_contract()

        dp = contract.price_dp

        side = None

        if target_qty > current_qty:
            side = "Ask"

        elif target_qty < current_qty:
            side = "Bid"

        price = self.get_best_price(side)

        # Adding the order to the top of the book by adding/subtracting one tick.
        if side == "Bid":
            price += contract.tick_size
        else:
            price -= contract.tick_size

        price = int(price * (10**dp))

        required_qty = abs(target_qty - current_qty)

        order = {
            'symbol': self.target_symbol,
            'side': side,
            'quantity': required_qty,
            'leverage': self.target_leverage,
            'price': price,
            'order_type': self.order_type,
            'margin_type': 'Isolated',
            'settlement_type': 'Instant',
            'ext_order_id': str(uuid.uuid4()),
        }
        self.logger.debug("New order: {}".format(order))

        self.place_order(order)

    def print_state(self, state):
        pprint(state.to_dict())
        pprint(self.master_wallet.to_dict())

    def update_node_info(self):
        try:
            node_info = self.lnd_client.get_info()
            self.node_info = {
                "alias": node_info.alias,
                "identity_pubkey": node_info.identity_pubkey,
                "num_active_channels": node_info.num_active_channels,
            }
        except Exception as e:
            self.logger.exception("Got exception on update_node_info: {}".format(e))

    def update_wallet_data(self):
        self.logger.debug("Update wallet balances.")
        usd_wallet = self.synth_wallets.get("USD")
        position = self.positions.get("BTCUSD.PERP")
        if position and position.quantity > 0:
            usd_wallet.available_balance = ((self.master_wallet.kollider_isolated_margin + float(position.upnl)) / 100000000) * self.current_mark_price 
            usd_wallet.balance = usd_wallet.available_balance
        else:
            usd_wallet.available_balance = 0
            usd_wallet.balance = 0
        self.synth_wallets["USD"] = usd_wallet
        btc_wallet = self.synth_wallets.get("BTC")
        btc_wallet.balance = 0
        btc_wallet.balance += self.master_wallet.kollider_cash
        btc_wallet.balance += self.master_wallet.channel_balance
        btc_wallet.balance += self.master_wallet.onchain_balance

    def update_master_wallet(self):
        self.logger.debug("Update master wallet balances.")
        channel_balances = self.lnd_client.get_channel_balances()
        onchain_balances = self.lnd_client.get_onchain_balance()
        self.master_wallet.update_channel_balance(channel_balances.balance)
        self.master_wallet.update_onchain_balance(onchain_balances.total_balance) 

    def cli(self):
        self.logger.info("Starting ln-hedghog CLI.")
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.connect(SOCKET_SUB_ADDRESS)
        socket.setsockopt(zmq.SUBSCRIBE, b'hedger_pub_stream')
        while True:
            message = ""
            try:
                message = socket.recv_json()
                print(message)
            except Exception as e:
                self.logger.debug("Error while receiving msg from zmq.")
                continue
            if message.get("action") is not None:
                action = message.get("action")
                data = message.get("data")
                if action == "get_hedge_state":
                    d = {
                        "state": self.to_dict()
                    }
                    self.publish_msg(d, "setHedgeState")
                    continue

                if action == "get_master_wallet_state":
                    d = {
                        "state": self.master_wallet.to_dict()
                    }
                    self.publish_msg(d, "getMasterWalletState")
                    continue

                if action == "get_synth_wallets":
                    d = {
                    }
                    for key, value in self.synth_wallets.items():
                        d[key] = value.to_dict()
                    self.publish_msg(d, "getSythWallets")
                    continue

                if action == "auth_hedger":
                    d = {
                        "status": "success"
                    }
                    if self.wst:
                        self.logger.debug("closing websockets")
                        self.ws.close()
                        self.logger.debug("websockets closed")
                    self.reconnect(self.settings["kollider"]["ws_url"])
                    self.logger.debug("reconnected")
                    self.set_jwt(data["token"])
                    self.publish_msg(d, "authHedger")
                    continue

                if action == "make_conversion":
                    if data["is_staged"]:
                        estimation = self.estimate_conversion(data["amount_in_dollar"])
                        data = estimation.to_dict()
                        self.publish_msg(data, "makeConversion")
                        continue
                    else:
                        self.make_conversion(data["amount_in_dollar"])
                    d = {
                        "status": "acknowledged"
                    }
                    self.publish_msg(data, "makeConversion")
                    continue

                if action == "create_invoice":
                    amount_in_sats = data["amount_in_sats"]
                    memo = data["memo"]
                    d = {}
                    try:
                        resp = self.lnd_client.add_invoice(amount_in_sats, memo)
                        d = {
                            "invoice": resp.payment_request
                        }
                    except Exception as e:
                        d = {"error": "{}".format(e)}
                    self.publish_msg(d, "createInvoice")
                    continue

                if action == "send_payment":
                    payment_request = data["payment_request"]
                    d = {}
                    try:
                        resp = self.lnd_client.send_payment(payment_request)
                        d = {
                            "status": "success"
                        }
                    except Exception as e:
                        d = {
                            "error": "{}".format(e)
                        }
                    self.publish_msg(d, "sendPayment")
                    continue

                if action == "lnurl_auth":
                    self.logger.debug("Performing lnurl auth.")
                    decoded_url = lnurl.decode(data["lnurl"])
                    try:
                        res = self.lnd_client.sign_message(SEED_WORD)
                        if res.signature == "":
                            self.logger.error("Error on lnurl_auth: {}".format(e))
                            d = {
                                "status": "error"
                            }
                            self.publish_msg(d, "lnurlAuth")
                            return
                    except Exception as e:
                        self.logger.error("Error on lnurl_auth: {}".format(e))
                        d = {
                            "status": "error"
                        }
                        self.publish_msg(d, "lnurlAuth")
                        return
                    lnurl_auth_signature = perform_lnurlauth(res.signature, decoded_url)
                    try:
                        _ = requests.get(lnurl_auth_signature)
                        d = {
                            "status": "success"
                        }
                        self.publish_msg(d, "lnurlAuth")
                    except Exception as e:
                        self.logger.error("Error on lnurl_auth: {}".format(e))
                    continue

                if action == "close_account":
                    self.target_dollar_amount = 0
                    self.settings["target_dollar_amount"] = 0
                    save_to_settings(self.settings)
                    d = {
                        "status": "closeAccount"
                    }
                    self.publish_msg(d, "closeAccount")

    def start(self, settings):
        cycle_speed = settings["cycle_speed"]

        self.set_params(**settings)
        self.settings = settings

        self.update_node_info()

        cli_thread = threading.Thread(target=self.cli, daemon=True , args=())
        cli_thread.start()

        self.logger.info("Starting ln hedgehog engine.")

        while True:
            self.logger.debug("Is CLI thread alive: {}".format(cli_thread.is_alive()))
            if not cli_thread.is_alive():
                cli_thread = threading.Thread(target=self.cli, daemon=True , args=())
                cli_thread.start()

            # Don't do anything if we haven't received the contracts.
            if not self.received_tradable_symbols and not self.is_kollider_authenticated:
                self.logger.debug("Not Kollider Authenticated")
                sleep(cycle_speed)
                continue

            # Don't do anything if we haven't received mark or index price.
            if self.current_index_price == 0 or self.current_mark_price == 0:
                continue

            # Don't do anything if we have no ticker price.
            if self.last_ticker.last_side is None:
                continue

            self.update_master_wallet()
            self.update_wallet_data()
            self.publish_synth_wallets()
            # self.estimate_hedge_price()

            # self.update_average_funding_rates()

            # Getting current state.
            state = self.build_target_state()
            # Printing the state.
            # Converging to that state.
            self.converge_state(state)
            self.sweep_excess_funds_from_kollide()

            sleep(cycle_speed)
