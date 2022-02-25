from ast import parse
from distutils.sysconfig import customize_compiler
from os import get_inheritable, environ
from random import seed
from kollider_api_client.ws import KolliderWsClient
from kollider_api_client.rest import KolliderRestClient
from utils import *
from lnd_client import LndClient
from kollider_msgs import OpenOrder, Position, TradableSymbol, Ticker
from time import sleep
from threading import Lock
import json
from math import floor
import uuid
from pprint import pprint
import threading
import lnurl
from lnurl.types import Url
from urllib.parse import urlparse, parse_qs
import requests
from lnurl_auth import perform_lnurlauth
import hashlib
from lnhedgehog import HedgerEngine
from utils import setup_custom_logger

class ReplaceClearnetUrl(Url):
    allowed_schemes = {"http", "https"}

def main():
    lnurl.types.ClearnetUrl = ReplaceClearnetUrl

    env = environ.get("ENV")

    file_name = "config/" + env + "." + "config.json"

    with open(file_name, 'w+') as a:
        settings = json.load(a)

    logger = setup_custom_logger("lnhedgehog", settings.get("log_level"))

    node_url = ""
    if environ.get("LND_IP") is None:
        node_url = settings["lnd"]["node_url"]
    else:
        node_url = f"{environ['LND_IP']}:10009"
    macaroon_path = settings["lnd"]["admin_macaroon_path"]
    tls_path = settings["lnd"]["tls_path"]

    lnd_client = LndClient(node_url, macaroon_path, tls_path, logger)
    rn_engine = HedgerEngine(lnd_client, logger)

    lock = Lock()

    hedger_thread = threading.Thread(
        target=rn_engine.start, daemon=True, args=(settings,))
    hedger_thread.start()

    while True:
        if not hedger_thread.is_alive():
            logger.error("Backend thread died. Attempting to recover.")
            hedger_thread = threading.Thread(
                target=rn_engine.start, daemon=True, args=(settings,))
            hedger_thread.start()


if __name__ in "__main__":
    main()