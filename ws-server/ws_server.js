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

let ZMQ_ADDRESS = "";
let ZMQ_SUB_ADDRESS = "";
let ZMQ_HEDGER_ADDRESS = "";

if (process.env.DEV) {
  ZMQ_SUB_ADDRESS = "tcp://127.0.0.1:5557";
  ZMQ_HEDGER_ADDRESS = "tcp://127.0.0.1:5558";
  ZMQ_HEDGER_SUB_ADDRESS = "tcp://127.0.0.1:5559";
} else {
  ZMQ_ADDRESS = process.env.ZONIC_ZMQ_ADDRESS;
  ZMQ_SUB_ADDRESS = process.env.ZONIC_ZMQ_SUB_ADDRESS;
  ZMQ_HEDGER_ADDRESS = process.env.ZONIC_ZMQ_HEDGER_ADDRESS;
  ZMQ_HEDGER_SUB_ADDRESS = process.env.ZONIC_ZMQ_HEDGER_SUB_ADDRESS;
}

const createResponse = (data, type) => {
  const resp = {
    type: type,
    data: data,
  };
  return JSON.stringify(resp);
};

async function zmqHedgerSubscriber(onMessage, isAuthenticated) {
  const subSocket = new zmq.Subscriber();

  await subSocket.connect(ZMQ_HEDGER_SUB_ADDRESS);
  subSocket.subscribe("hedger_stream");

  for await (const [topic, msg] of subSocket) {
    onMessage(msg);
  }
}

async function zmqHedgerRequest(msg, onReply) {
  // const socket = new zmq.Request({ sendTimeout: 2000, receiveTimeout: 3000 });
  const socket = new zmq.Request();
  socket.connect(ZMQ_HEDGER_ADDRESS);
  try {
    await socket.send(msg);
  } catch (err) {
    console.log(err)
    return
  }
  try {
    const [result] = await socket.receive();
    onReply(result);
  } catch (err) {
    console.log(err)
    return
  }
}

const wss = new ws.WebSocketServer({
  port: 8080,
  perMessageDeflate: false,
});

const onAuth = () => { };

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
      console.log(d)
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
        zmqHedgerSubscriber(onZmqReply);
        return;
      } else {
        const data = {
          msg: "wrong password",
        };
        ws.send(createResponse(data, "authentication"));
      }
    }

    if (!isAuthenticated) {
      const response = createResponse({ msg: "Please Authenticate." }, "error");
      ws.send(response.toString());
      return;
    } else if (d.type === LNURL_AUTH) {
      const msg = {
        action: "lnurl_auth",
        data: { lnurl: d.lnurl },
      };
      zmqLndRequest(JSON.stringify(msg), onZmqReply);
    } else if (d.type === AUTH_HEDGER) {
      const msg = {
        action: "auth_hedger",
        data: { token: d.token },
      };
      console.log(msg)
      zmqHedgerRequest(JSON.stringify(msg), onZmqReply);
    } else if (d.type === GET_HEDGE_STATE) {
      const msg = {
        action: "get_hedge_state",
      };
      zmqHedgerRequest(JSON.stringify(msg), onZmqReply);
    } else if (d.type === GET_WALLET_STATE) {
      const msg = {
        action: "get_master_wallet_state",
      };
      zmqHedgerRequest(JSON.stringify(msg), onZmqReply);
    } else if (d.type === GET_SYNTH_WALLETS) {
      const msg = {
        action: "get_synth_wallets",
      };
      zmqHedgerRequest(JSON.stringify(msg), onZmqReply);
    } else if (d.type === MAKE_CONVERSION) {
      const msg = {
        action: "make_conversion",
        data: {
          amount_in_dollar: d.amountInDollar,
          is_staged: d.isStaged
        }
      };
      zmqHedgerRequest(JSON.stringify(msg), onZmqReply);
    } else if (d.type === CREATE_INVOICE) {
      if (!d.amountInSats) return
      const msg = {
        action: "create_invoice",
        data: {
          amount_in_sats: d.amountInSats,
          memo: d.memo
        }
      };
      zmqHedgerRequest(JSON.stringify(msg), onZmqReply);
    } else if (d.type === SEND_PAYMENT) {
      const msg = {
        action: "send_payment",
        data: {
          payment_request: d.paymentRequest,
        }
      };
      zmqHedgerRequest(JSON.stringify(msg), onZmqReply);
    } else {
      ws.send(createResponse({ msg: "action not available" }, "error"));
    }
  });
});
