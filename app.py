from flask import Flask, request, redirect, render_template_string, abort
import sqlite3, secrets, os, time, hmac, hashlib, requests
from datetime import datetime, timedelta

app = Flask(__name__)
DB = "vales.db"

ADMIN = r'''<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sistema de Vale</title>
<style>
body{font-family:Arial;background:#f3f5f8;margin:0}.wrap{max-width:1100px;margin:auto;padding:18px}
.card{background:white;border-radius:18px;padding:20px;margin:14px 0;overflow:auto}
input{width:100%;padding:13px;box-sizing:border-box;margin:7px 0 12px;border:1px solid #ccd2da;border-radius:10px;font-size:16px}
button,.btn{display:inline-block;padding:13px 18px;background:#111827;color:white;border:0;border-radius:10px;font-weight:bold;text-decoration:none}
table{width:100%;border-collapse:collapse;min-width:850px}td,th{text-align:left;padding:9px;border-bottom:1px solid #eee}
.small{font-size:13px;color:#555}
</style>
<div class="wrap">
<div class="card"><h1>🎁 Sistema de Vale</h1>
<p>Total: <b>{{total}}</b> | Disponibles: <b>{{available}}</b> | Canjeados: <b>{{redeemed}}</b></p>
<a class="btn" href="/binance-test">Probar conexión con Binance</a>
<p class="small">Prueba de solo lectura. No compra, vende ni transfiere dinero.</p></div>
<div class="card"><h2>Crear vale</h2>
<form method="post" action="/admin/create">
<label>Monto USDT</label><input name="amount" type="number" min=".01" step=".01" value="50" required>
<label>Vencimiento (días)</label><input name="days" type="number" min="1" value="30" required>
<button>Generar vale</button></form></div>
<div class="card"><h2>Registro</h2><table>
<tr><th>Vale</th><th>USDT</th><th>Estado</th><th>Creado</th><th>Canjeado</th><th>Binance ID</th><th>IP</th></tr>
{% for v in vals %}<tr><td><a href="/admin/vale/{{v['code']}}">{{v['code']}}</a></td>
<td>{{'%.2f'|format(v['amount'])}}</td><td>{{v['status']}}</td><td>{{v['created_at']}}</td>
<td>{{v['redeemed_at'] or '-'}}</td><td>{{v['binance_id'] or '-'}}</td><td>{{v['redeemed_ip'] or '-'}}</td></tr>{% endfor %}
</table></div></div>'''

VALE = r'''<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Vale</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<style>body{font-family:Arial;background:#f3f5f8}.card{background:white;max-width:500px;margin:25px auto;padding:22px;border-radius:18px;text-align:center}.amount{font-size:40px;font-weight:800}.qr{display:flex;justify-content:center;margin:20px}</style>
<div class="card"><h1>🎁 Vale Digital</h1><div class="amount">{{'%.2f'|format(v['amount'])}} USDT</div><p>{{v['code']}}</p><div class="qr" id="qr"></div><p>Escanea este QR para canjear.</p></div>
<script>new QRCode(document.getElementById('qr'),{text:{{url|tojson}},width:240,height:240})</script>'''

CANJE = r'''<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Canjear Vale</title>
<style>body{font-family:Arial;background:#f3f5f8}.card{background:white;max-width:500px;margin:25px auto;padding:22px;border-radius:18px}.amount{text-align:center;font-size:40px;font-weight:800}input{width:100%;box-sizing:border-box;padding:14px;border:1px solid #ccd2da;border-radius:10px;font-size:17px}button{width:100%;padding:14px;margin-top:14px;background:#111827;color:white;border:0;border-radius:10px;font-weight:bold}.ok{background:#e8f7ed;color:#16743b;padding:9px;text-align:center;border-radius:20px}.bad{background:#fdecec;color:#b42318;padding:9px;text-align:center;border-radius:20px}</style>
<div class="card"><h1>🎁 Canjear Vale</h1><div class="amount">{{'%.2f'|format(v['amount'])}} USDT</div><p style="text-align:center">{{v['code']}}</p>
{% if v['status']=='DISPONIBLE' and not expired %}<div class="ok">DISPONIBLE</div><form method="post"><p>Binance ID</p><input name="binance_id" inputmode="numeric" required placeholder="Ej. 123456789"><button>Canjear Vale</button></form>
{% else %}<div class="bad">VALE NO DISPONIBLE</div>{% endif %}</div>'''

OK = r'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#f3f5f8}.card{background:white;max-width:500px;margin:40px auto;padding:25px;border-radius:18px;text-align:center}.big{font-size:55px}</style><div class="card"><div class="big">✅</div><h1>Vale canjeado</h1><h2>{{'%.2f'|format(v['amount'])}} USDT</h2><p>Binance ID: <b>{{v['binance_id']}}</b></p><p>Modo prueba: no se movió dinero real.</p></div>'''

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS vouchers(id INTEGER PRIMARY KEY,code TEXT UNIQUE,amount REAL,status TEXT,created_at TEXT,expires_at TEXT,binance_id TEXT,redeemed_at TEXT,redeemed_ip TEXT)''')
    c.commit(); return c

def newcode(): return "V-"+secrets.token_hex(3).upper()+"-"+secrets.token_hex(2).upper()
def client_ip():
    forwarded=request.headers.get("X-Forwarded-For","")
    return forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "")

@app.get("/")
def home(): return redirect("/admin")

@app.get("/admin")
def admin():
    c=db(); vals=c.execute("SELECT * FROM vouchers ORDER BY id DESC").fetchall()
    return render_template_string(ADMIN,vals=vals,total=len(vals),available=sum(v["status"]=="DISPONIBLE" for v in vals),redeemed=sum(v["status"]=="CANJEADO" for v in vals))

@app.post("/admin/create")
def create():
    try: amount=float(request.form["amount"]); days=int(request.form["days"])
    except (ValueError,KeyError): return "Datos inválidos",400
    if amount<=0 or days<=0: return "El monto y los días deben ser mayores que cero",400
    now=datetime.utcnow(); code=newcode(); c=db()
    c.execute("INSERT INTO vouchers(code,amount,status,created_at,expires_at,binance_id,redeemed_at,redeemed_ip) VALUES(?,?,?,?,?,?,?,?)",(code,amount,"DISPONIBLE",now.isoformat(),(now+timedelta(days=days)).isoformat(),"","","")); c.commit()
    return redirect("/admin/vale/"+code)

@app.get("/admin/vale/<code>")
def show(code):
    c=db(); v=c.execute("SELECT * FROM vouchers WHERE code=?",(code,)).fetchone()
    if not v: abort(404)
    return render_template_string(VALE,v=v,url=request.url_root.rstrip("/")+"/vale/"+code)

@app.route("/vale/<code>",methods=["GET","POST"])
def redeem(code):
    c=db(); v=c.execute("SELECT * FROM vouchers WHERE code=?",(code,)).fetchone()
    if not v: abort(404)
    expired=datetime.utcnow()>datetime.fromisoformat(v["expires_at"])
    if request.method=="POST" and v["status"]=="DISPONIBLE" and not expired:
        bid=request.form.get("binance_id","").strip()
        if not bid.isdigit() or not 5<=len(bid)<=20: return "Binance ID inválido",400
        cur=c.execute("UPDATE vouchers SET status='CANJEADO',binance_id=?,redeemed_at=?,redeemed_ip=? WHERE code=? AND status='DISPONIBLE'",(bid,datetime.utcnow().isoformat(),client_ip(),code)); c.commit()
        if cur.rowcount==1:
            v=c.execute("SELECT * FROM vouchers WHERE code=?",(code,)).fetchone()
            return render_template_string(OK,v=v)
        v=c.execute("SELECT * FROM vouchers WHERE code=?",(code,)).fetchone()
    return render_template_string(CANJE,v=v,expired=expired)

@app.get("/binance-test")
def binance_test():
    key=os.getenv("BINANCE_API_KEY",""); secret=os.getenv("BINANCE_API_SECRET","")
    if not key or not secret: return "Faltan BINANCE_API_KEY o BINANCE_API_SECRET en Render",500
    query="recvWindow=5000&timestamp="+str(int(time.time()*1000))
    signature=hmac.new(secret.encode(),query.encode(),hashlib.sha256).hexdigest()
    try:
        response=requests.get("https://api.binance.com/api/v3/account?"+query+"&signature="+signature,headers={"X-MBX-APIKEY":key},timeout=15)
        if response.ok: return "<h2>✅ Conexión con Binance exitosa.</h2><p>No se movió dinero.</p>"
        return f"<h2>❌ Binance respondió {response.status_code}.</h2><p>Revisa permisos y claves.</p>",502
    except requests.RequestException: return "<h2>❌ No se pudo conectar con Binance.</h2>",502

if __name__=="__main__": db(); app.run(host="0.0.0.0",port=5000)
