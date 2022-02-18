import requests

def get_historical_trades(url, token, symbol, limit):
	route = "/user/trades"
	endpoint = url + route
	params = "?symbol={}&limit={}".format(symbol, limit)
	endpoint += params
	try:
		headers = {"Authorization": "{}".format(token)}
		resp = requests.get(endpoint, headers=headers)
		return resp.json()
	except Exception as e:
		print(e)