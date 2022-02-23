const ws = require("ws");
const zmq = require("zeromq");

const AUTHENTICATION = "authentication";
const SEND_PAYMENT = "sendPayment";
const CREATE_INVOICE = "createInvoice";
const GET_CHANNEL_BALANCES = "getChannelBalances";
const GET_WALLET_BALANCES = "getWalletBalances";
const GET_NODE_INFO = "getNodeInfo";
const GET_HEDGE_STATE = "getHedgeState";
const GET_WALLET_STATE = "getWalletState";
const GET_SYNTH_WALLETS = "getSynthWallets";
const SET_TARGET_HEDGE = "setTargetHedge";
const LNURL_AUTH = "lnurlAuth";
const MAKE_CONVERSION = "makeConversion";
const AUTH_HEDGER = "authHedger";
const CLOSE_ACCOUNT = "closeAccount";
const LOGOUT = "logout";
const GET_HISTORICAL_TRADES = "getHistoricalTrades";
const RESTART = "restart";

if (process.env.DEV) {
  ZMQ_HEDGER_PUB_ADDRESS = "tcp://127.0.0.1:5558";
  ZMQ_HEDGER_SUB_ADDRESS = "tcp://127.0.0.1:5559";
} else {
  ZMQ_HEDGER_PUB_ADDRESS = process.env.ZONIC_ZMQ_HEDGER_ADDRESS;
  ZMQ_HEDGER_SUB_ADDRESS = process.env.ZONIC_ZMQ_HEDGER_SUB_ADDRESS;
}

const createResponse = (data, type) => {
  const resp = {
    type: type,
    data: data,
  };
  return JSON.stringify(resp);
};

async function zmqSubscriber(onMessage) {
  const subSocket = new zmq.Subscriber();

  await subSocket.connect(ZMQ_HEDGER_SUB_ADDRESS);
  subSocket.subscribe("hedger_sub_stream");

  for await (const [topic, msg] of subSocket) {
    onMessage(msg);
  }
}

const wss = new ws.WebSocketServer({
  port: 8080,
  perMessageDeflate: false,
});

const pubSocket = new zmq.Publisher();

pubSocket.bind(ZMQ_HEDGER_PUB_ADDRESS).then(_ => {
  const sendToBack = (msg) => {
    pubSocket.send(["hedger_pub_stream", msg])
  }
  wss.on("connection", function connection(ws) {
    let isAuthenticated = false;
    const onZmqReply = (msg) => {
      let jstring = msg.toString();
      try {
        jstring = JSON.parse(jstring);
        jstring.map((m) => {
          ws.send(JSON.stringify(m));
        });
      } catch (err) {
        console.log(err)
      }
    };

    ws.on("message", function message(data) {
      let d = "";
      try {
        d = JSON.parse(data);
        // console.log(d)
      } catch (err) {
        return null;
      }
      if (d.type === AUTHENTICATION) {
        let env_password = process.env.APP_PASSWORD;
        if (d.password === env_password && !isAuthenticated) {
          const data = {
            status: "success",
          };
          isAuthenticated = true;
          ws.send(createResponse(data, "authentication"));
          zmqSubscriber(onZmqReply);
          return;
        } else {
          const data = {
            msg: "wrong password",
          };
          ws.send(createResponse(data, "authentication"));
          return
        }
      }

      if (!isAuthenticated) {
        const response = createResponse({ msg: "Please Authenticate." }, "error");
        ws.send(response.toString());
        return;
      } else if (d.type === GET_HEDGE_STATE) {
        const msg = {
          action: "get_hedge_state",
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === GET_WALLET_STATE) {
        const msg = {
          action: "get_master_wallet_state",
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === GET_SYNTH_WALLETS) {
        const msg = {
          action: "get_synth_wallets",
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === MAKE_CONVERSION) {
        const msg = {
          action: "make_conversion",
          data: {
            amount_in_dollar: d.amountInDollar,
            is_staged: d.isStaged
          }
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === CREATE_INVOICE) {
        if (!d.amountInSats) return
        const msg = {
          action: "create_invoice",
          data: {
            amount_in_sats: d.amountInSats,
            memo: d.memo
          }
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === SEND_PAYMENT) {
        const msg = {
          action: "send_payment",
          data: {
            payment_request: d.paymentRequest,
          }
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === CLOSE_ACCOUNT) {
        const msg = {
          action: "close_account",
          data: {
          }
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === GET_HISTORICAL_TRADES) {
        const msg = {
          action: "get_historical_trades",
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === RESTART) {
        const msg = {
          action: "restart",
        };
        sendToBack(JSON.stringify(msg));
      } else if (d.type === LOGOUT) {
        data = {
          "status": "success"
        }
        ws.send(createResponse(data, "logout"));
        ws.close()
      } else {
        ws.send(createResponse({ msg: "action not available" }, "error"));
      }
    });
  });
})
