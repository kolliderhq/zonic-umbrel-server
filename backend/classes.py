import time

class HedgerState(object):
    position_quantity = 0
    ask_open_order_quantity = 0
    bid_open_order_quantity = 0
    target_quantity = 0
    target_value = 0
    is_locking = False
    lock_price = None
    side = None
    predicted_funding_payment = 0

    def to_dict(self):
        return {
            "position_quantity": self.position_quantity,
            "bid_open_order_quantity": self.bid_open_order_quantity,
            "ask_open_order_quantity": self.ask_open_order_quantity,
            "target_quantity": self.target_quantity,
            "target_value": self.target_value,
            "is_locking": self.is_locking,
            "lock_price": self.lock_price,
            "side": self.side,
            "predicted_funding_payment": self.predicted_funding_payment
        }

class ConversionEstimation(object):
    def __init__(self):
        self.btc_value = 0
        self.usd_value = 0
        self.fees = 0
        self.estimated_fill_price = 0
        self.is_error = False
        self.error_reason = ""

    def to_dict(self):
        return {
            "btc_value": self.btc_value,
            "usd_value": self.usd_value,
            "fees": self.fees,
            "estimated_fill_price": self.estimated_fill_price,
            "is_error": self.is_error,
            "error_reason": self.error_reason
        }

## This is the wallet actually representing value
## on the LND node or on Kollider.
class MasterWallet(object):

    def __init__(self):
        self.channel_balance = 0
        self.onchain_balance = 0
        self.kollider_isolated_margin = 0
        self.kollider_order_margin = 0
        self.kollider_cash = 0

    def update_channel_balance(self, balance):
        self.channel_balance = balance

    def update_onchain_balance(self, balance):
        self.onchain_balance = balance

    def update_kollider_isolated_margin(self, balance):
        self.kollider_isolated_margin = balance

    def update_kollider_order_margin(self, balance):
        self.kollider_order_margin = balance

    def update_kollider_cash(self, balance):
        self.kollider_cash = balance

    def to_dict(self):
        return {
            "channel_balance": self.channel_balance,
            "onchain_balance": self.onchain_balance,
            "kollider_isolatde_margin": self.kollider_isolated_margin,
            "kollider_order_margin": self.kollider_order_margin,
            "kollider_cash": self.kollider_cash
        }

    def total_ln_balance(self):
        return self.channel_balance + self.kollider_cash

## This is a synthetic wallet representing synthetic value.
class SynthWallet(object):
    def __init__(self, currencySymbol):
        self.currencySymbol = currencySymbol
        self.balance = 0
        self.available_balance = 0
        self.denomination = ""
        self.increment = 1
        self.dp = 0

    def __repr__(self) -> str:
        return "<{} Wallet Value: {}>".format(self.currencySymbol, self.balance)

    def setBalance(self, balance):
        self.balance = balance

    def setDp(self, dp):
        self.dp = dp
    
    def setAvailable(self, available_balance):
        self.available_balance = available_balance

    def setDenomination(self, denomination):
        self.denomination = denomination

    def getBalance(self):
        return self.balance

    def to_dict(self):
        return {
            "currency_symbol": self.currencySymbol,
            "balance": self.balance,
            "available_balance": self.available_balance,
            "denomination": self.denomination,
            "increment": self.increment,
            "dp": self.dp,
        }


class KolliderWithdrawalState(object):
    def __init__(self):
        self.in_progress = False
        self.started = time.time()

    def set_in_progress(self):
        self.in_progress = True

    def finished(self):
        self.in_progress = False
    
    def reset_time(self):
        self.started = time.time()