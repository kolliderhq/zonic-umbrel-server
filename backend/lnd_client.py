import lightning_pb2 as ln
import lightning_pb2_grpc as lnrpc
import grpc
import os
import codecs
import threading
from time import sleep

os.environ["GRPC_SSL_CIPHER_SUITES"] = 'HIGH+ECDSA'

class LndClient(object):
	def __init__(self, node_url, macaroon_path, tls_path, logger):

		cert = open(os.path.expanduser(tls_path), 'rb').read()
		creds = grpc.ssl_channel_credentials(cert)
		channel = grpc.secure_channel(node_url, creds)
		self.stub = lnrpc.LightningStub(channel)

		with open(os.path.expanduser(macaroon_path), 'rb') as f:
			macaroon_bytes = f.read()
			self.macaroon = codecs.encode(macaroon_bytes, 'hex')
		self.node_url = node_url

	def sub_invoices(self, callback):
		request = ln.InvoiceSubscription()
		try:
			for invoice in self.stub.SubscribeInvoices(request, metadata=[('macaroon', self.macaroon)]):
				callback(invoice)
		except Exception as err:
			sleep(5)
			print(err)
			print("Trying to connect to invoices again.")
			self.sub_invoices(callback)

	def get_info(self):
		return self.stub.GetInfo(ln.GetInfoRequest(), metadata=[('macaroon', self.macaroon)])

	def get_onchain_balance(self):
		return self.stub.WalletBalance(ln.WalletBalanceRequest(), metadata=[('macaroon', self.macaroon)])

	def get_channel_balances(self):
		return self.stub.ChannelBalance(ln.ChannelBalanceRequest(), metadata=[('macaroon', self.macaroon)])

	def send_payment(self, payment_request):
		send_request = ln.SendRequest(payment_request=payment_request)
		return self.stub.SendPaymentSync(send_request, metadata=[('macaroon', self.macaroon)])

	def add_invoice(self, amount, memo):
		invoice = ln.Invoice(value=amount, memo=memo)
		return self.stub.AddInvoice(invoice, metadata=[('macaroon', self.macaroon)])

	def sign_message(self, msg):
		message = ln.SignMessageRequest(msg=msg)
		return self.stub.SignMessage(message, metadata=[('macaroon', self.macaroon)])


if __name__ in "__main__":
	pass
