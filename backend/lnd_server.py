from urllib import response
from utils import *
from lnd_client import LndClient
from time import sleep
from threading import Lock
import json
import threading
import lnurl
from urllib.parse import urlparse, parse_qs
import requests
from lnurl_auth import perform_lnurlauth
import hashlib
import zmq
from utils import setup_custom_logger

SOCKET_ADDRESS = "tcp://*:5556"
SOCKET_PUB_ADDRESS = "tcp://*:5557"

SEED_WORD = hashlib.sha256("cheers to you until all enternity and here is my entry ser.".encode("utf-8")).digest()

def lnd_invoice_publisher(ln_client):
	context = zmq.Context()
	socket = context.socket(zmq.PUB)
	socket.bind(SOCKET_PUB_ADDRESS)
	def on_invoice(invoice):
		data = {
			"payment_request": invoice.payment_request,
			"value": invoice.value,
			"settled": invoice.settled
		}
		if data["settled"]:
			response = {
				"type": "receivedPayment",
				"data": {
					"payment_request": data["payment_request"],
					"amount": data["value"]
				}
			}
			socket.send_multipart(["invoices".encode("utf-8"), json.dumps([response]).encode("utf8")])
	# ln_client.sub_invoices(on_invoice)
	invoice_publish_thread = threading.Thread(
		target=ln_client.sub_invoices, daemon=True, args=(on_invoice, ))
	invoice_publish_thread.start()
	while True:
		try:
			res = ln_client.get_channel_balances()
			response = {
				"type": "getChannelBalances",
				"data": {
					"local": res.local_balance.sat,
					"localMsat": res.local_balance.msat,
					"remote": res.remote_balance.sat,
					"remoteMsat": res.remote_balance.msat
				}
			}
			# socket.send_multipart(["invoices".encode("utf-8"), json.dumps([response]).encode("utf8")])
			sleep(3)
		except Exception as e:
			print("Error getting channel balances: {}".format(e))

def lnd_node_server(lnd_client, logger):
	logger.debug("Started LND node server.")
	context = zmq.Context()
	socket = context.socket(zmq.REP)
	socket.bind(SOCKET_ADDRESS)
	while True:
		message = ""
		try:
			message = socket.recv_json()
		except Exception as e:
			logger.error("Error while receiving msg from zmq.")
			continue
		if message.get("action") is not None:
			action = message.get("action")
			data = message.get("data")
			logger.debug("Action received: {}".format(action))
			logger.debug("Data received: {}".format(data))
			if action == "get_node_info":
				res = lnd_client.get_info()
				response = {
					"type": "getNodeInfo",
					"data": {
						"identity_pubkey": res.identity_pubkey,
						"alias": res.alias,
						"num_active_channels": res.num_active_channels,
						"num_peers": res.num_peers,
						"block_height": res.block_height,
						"block_hash": res.block_hash,
						"synced_to_chain": res.synced_to_chain,
						"best_header_timestamp": res.best_header_timestamp,
						"version": res.version, 
						"color": res.color,
						"synced_to_graph": res.synced_to_graph
					}
				}
				socket.send_json([response])
				continue
			if action == "create_invoice":
				message = "kollider"
				res = lnd_client.add_invoice(data["amount"], message)
				response = {
					"type": "createInvoice",
					"data": {
						"paymentRequest": res.payment_request
					}
				}
				socket.send_json([response])
				continue
			if action == "send_payment":
				resp = []
				try:
					res = lnd_client.send_payment(data["payment_request"])
					response = {
						"type": "sendPayment",
						"data": {
							"status": "success",
						}
					}
					resp.append(response)
				except Exception as err:
					resp.append({"type": "error", "data": {"msg": "Failed sending payment."}})
				try:
					res = lnd_client.get_channel_balances()
					response = {
						"type": "getChannelBalances",
						"data": {
							"local": res.local_balance.sat,
							"localMsat": res.local_balance.msat,
							"remote": res.remote_balance.sat,
							"remoteMsat": res.remote_balance.msat
						}
					}
					resp.append(response)
				except Exception as e:
					resp.append({"type": "error", "data": {"msg": "Failed sending payment."}})
				socket.send_json(resp)
				continue
			if action == "get_channel_balances":
				res = lnd_client.get_channel_balances()
				response = {
					"type": "getChannelBalances",
					"data": {
						"local": res.local_balance.sat,
						"localMsat": res.local_balance.msat,
						"remote": res.remote_balance.sat,
						"remoteMsat": res.remote_balance.msat
					}
				}
				socket.send_json([response])
				continue
			if action == "get_wallet_balances":
				res = lnd_client.get_onchain_balance()
				response = {
					"type": "getWalletBalances",
					"data": {
						"confirmed_balance": res.confirmed_balance,
						"total_balance": res.total_balance,
					}
				}
				socket.send_json([response])
				continue
			if action == "lnurl_auth":
				decoded_url = lnurl.decode(data["lnurl"])
				try:
					res = lnd_client.sign_message(SEED_WORD)
					if res.signature == "":
						logger.error("Error on lnurl_auth: {}".format(e))
						response = {
							"type": "lnurl_auth",
							"data": {
								"status": "error"
							}
						}
						socket.send_json([response])
						return
				except Exception as e:
					logger.error("Error on lnurl_auth: {}".format(e))
					response = {
						"type": "lnurl_auth",
						"data": {
							"status": "error"
						}
					}
					socket.send_json([response])
					return
				lnurl_auth_signature = perform_lnurlauth(res.signature, decoded_url)
				try:
					_ = requests.get(lnurl_auth_signature)
					response = {
						"type": "lnurlAuth",
						"data": {
							"status": "success"
						}
					}
					socket.send_json([response])
				except Exception as e:
					logger.error("Error on lnurl_auth: {}".format(e))
				continue
			if action == "lnurl_auth_hedge":
				response = requests.get("https://api.kollider.xyz/v1/auth/external/lnurl_auth")
				j = response.json()
				decoded_url = lnurl.decode(j["lnurl_auth"])
				res = lnd_client.sign_message(SEED_WORD)
				sig1 = res.signature
				sig2 = hashlib.sha224((sig1 + "/1").encode("utf-8")).digest()
				res = lnd_client.sign_message(sig2)
				lnurl_auth_signature = perform_lnurlauth(res.signature, decoded_url)
				try:
					_ = requests.get(lnurl_auth_signature)
					response = {
						"type": "lnurl_auth",
						"data": {
							"status": "success"
						}
					}
					socket.send_json([response])
				except Exception as e:
					logger.error("Error on lnurl_auth_hedge: {}".format(e))
				continue
		sleep(0.5)

if __name__ in "__main__":
	url = "lnurl1dp68gup69uhkzurf9eehgct8d9hxwtntdakxc6tyv4ezu6tww3jhymnpdshhvvf0v96hg6p0d3h97mr0va5ku0m5v9nn6mr0va5kufntxy7nqc3cv9nrsvnrvfnrvvp5vcmnyvt9v4jx2e3nvs6rgvnrxgursc3hvg6kyenp8qmrgc34x3snjcnzxqurwwr9vymxvwfj8p3rwerrx5r0d7vc"
	decoded_url = lnurl.decode(url)
