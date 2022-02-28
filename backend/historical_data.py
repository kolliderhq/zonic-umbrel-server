from socket import timeout
import requests

def get_historical_trades(url, token, symbol, limit):
	route = "/user/trades"
	endpoint = url + route
	params = "?symbol={}&limit={}".format(symbol, limit)
	endpoint += params
	try:
		headers = {"Authorization": "{}".format(token)}
		resp = requests.get(endpoint, headers=headers, timeout=10)
		if resp.status_code == 200:
			return {
				"status": "success",
				"data": resp.json()
			}
		elif resp.status_code == 401: 
			return {
				"status": "error",
				"data": "unauthorized"
			}
		else:
			return {
				"status": "error",
				"data": resp
			}
	except Exception as e:
		print(e)
		raise e