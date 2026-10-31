import csv
import html
import io
import os
import secrets
from pathlib import Path
from typing import Generator

import requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pwdlib import PasswordHash
from sqlalchemy import Boolean, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "user_data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "")
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'video_facebook.db').as_posix()}")
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0")

if len(APP_SECRET_KEY) < 32:
    raise RuntimeError("Set APP_SECRET_KEY to a random secret of at least 32 characters.")
if not TOKEN_ENCRYPTION_KEY:
    raise RuntimeError("Set TOKEN_ENCRYPTION_KEY to a Fernet key generated with Fernet.generate_key().")

try:
    cipher = Fernet(TOKEN_ENCRYPTION_KEY.encode("ascii"))
except (ValueError, TypeError):
    raise RuntimeError("TOKEN_ENCRYPTION_KEY is invalid. Generate a Fernet key.")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
password_hash = PasswordHash.recommended()

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    encrypted_meta_token: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    rows_count: Mapped[int] = mapped_column(Integer, default=0)

class ConnectedPage(Base):
    __tablename__ = "connected_pages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    page_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(255))
    encrypted_page_token: Mapped[str] = mapped_column(String(4096))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)

Base.metadata.create_all(engine)

app = FastAPI(title="Video Facebook")
app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SECRET_KEY,
    session_cookie="vf_session",
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "true").lower() == "true",
    max_age=60 * 60 * 24 * 7,
)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token

def check_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Invalid form token. Refresh the page and try again.")

def current_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("user_id")
    if not isinstance(uid, int):
        return None
    user = db.get(User, uid)
    return user if user and user.active else None

def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root{{--bg:#101827;--panel:#1b293b;--text:#f4f7fb;--muted:#aab8ca;--accent:#2f80ed;--line:#34445b}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(135deg,#101827,#172b40);color:var(--text);font:16px Arial,sans-serif;min-height:100vh}}
main{{max-width:850px;margin:40px auto;padding:20px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px;margin:16px 0;box-shadow:0 12px 35px #0003}}
h1,h2{{margin-top:0}}p,.muted{{color:var(--muted);line-height:1.6}}label{{display:block;margin:14px 0 6px}}input{{width:100%;padding:12px;border-radius:9px;border:1px solid var(--line);background:#101827;color:white}}
button,.btn{{display:inline-block;background:var(--accent);color:white;border:0;border-radius:9px;padding:12px 18px;margin-top:14px;text-decoration:none;cursor:pointer}}
a{{color:#8fc3ff}}.row{{display:flex;gap:12px;flex-wrap:wrap}}.row>*{{flex:1}}small{{color:var(--muted)}}.notice{{padding:12px;background:#203a53;border-radius:9px}}
</style></head><body><main><h1>🎬 Video Facebook</h1>{body}</main></body></html>""")

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    body = """
    <section class="card"><h2>Publish videos to your Facebook Page</h2>
    <p>Create your own account. Your uploads and Facebook connection are kept separate from other users.</p>
    <div class="row"><a class="btn" href="/register">Create account</a><a class="btn" href="/login">Log in</a></div></section>
    <p class="muted">Private beta setup. Meta permissions and public deployment are still required.</p>"""
    return page("Welcome", body)

@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    token = csrf_token(request)
    return page("Create account", f"""
    <section class="card"><h2>Create account</h2>
    <form method="post"><input type="hidden" name="csrf" value="{token}">
    <label>Email</label><input type="email" name="email" required maxlength="320" autocomplete="email">
    <label>Password (at least 12 characters)</label><input type="password" name="password" required minlength="12" autocomplete="new-password">
    <button>Create account</button></form><p><a href="/login">Already registered? Log in</a></p></section>""")

@app.post("/register")
def register(request: Request, email: str = Form(...), password: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    email = email.strip().lower()
    if len(email) > 320 or "@" not in email or len(password) < 12:
        raise HTTPException(400, "Enter a valid email and a password of at least 12 characters.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, password_hash=password_hash.hash(password))
    db.add(user)
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    token = csrf_token(request)
    return page("Log in", f"""
    <section class="card"><h2>Log in</h2>
    <form method="post"><input type="hidden" name="csrf" value="{token}">
    <label>Email</label><input type="email" name="email" required autocomplete="email">
    <label>Password</label><input type="password" name="password" required autocomplete="current-password">
    <button>Log in</button></form><p><a href="/register">Create account</a></p></section>""")

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not user.active or not password_hash.verify(password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=303)

@app.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uploads = db.scalars(select(Upload).where(Upload.user_id == user.id).order_by(Upload.id.desc())).all()
    pages = db.scalars(select(ConnectedPage).where(ConnectedPage.user_id == user.id).order_by(ConnectedPage.name)).all()
    token = csrf_token(request)
    items = "".join(f"<li>{html.escape(u.original_name)} — {u.rows_count} rows</li>" for u in uploads) or "<li>No CSV uploaded yet.</li>"
    page_items = "".join(
        f"<li>{html.escape(p.name)} {'(selected)' if p.selected else ''}"
        f"<form method='post' action='/select-page'><input type='hidden' name='csrf' value='{token}'>"
        f"<input type='hidden' name='page_id' value='{html.escape(p.page_id, quote=True)}'>"
        f"<button>Select this Page</button></form></li>" for p in pages
    ) or "<li>No Pages loaded yet. Click Refresh Pages after connecting Meta.</li>"
    connected = "Connected token is saved encrypted." if user.encrypted_meta_token else "Facebook is not connected yet."
    body = f"""
    <section class="card"><h2>Your dashboard</h2><p>Signed in as {html.escape(user.email)}</p>
    <p class="notice">{connected}</p>
    <h3>Connect your Facebook account</h3>
    <p class="muted">Temporary developer setup: paste a User Access Token generated for your own Meta account. Never share it. This form sends it to this server over HTTPS and stores it encrypted. OAuth login will replace this manual step before public launch.</p>
    <form method="post" action="/connect-token"><input type="hidden" name="csrf" value="{token}">
    <label>Meta User Access Token</label><input type="password" name="access_token" required autocomplete="off">
    <button>Save encrypted token</button></form>
    <form method="post" action="/refresh-pages"><input type="hidden" name="csrf" value="{token}">
    <button>Refresh my Facebook Pages</button></form>
    <h3>Choose the Page for publishing</h3><ul>{page_items}</ul></section>
    <section class="card"><h3>Upload your CSV</h3><p class="muted">CSV must contain a Video Url / Video URL column. Uploads are private to your account.</p>
    <form method="post" action="/upload" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{token}">
    <input type="file" name="file" accept=".csv,text/csv" required><button>Upload CSV</button></form></section>
    <section class="card"><h3>Your files</h3><ul>{items}</ul>
    <p class="muted">Publishing worker and per-user checkpoint are not enabled yet. Uploading a file does not publish it.</p>
    <form method="post" action="/logout"><input type="hidden" name="csrf" value="{token}"><button>Log out</button></form></section>"""
    return page("Dashboard", body)

@app.post("/connect-token")
def connect_token(request: Request, access_token: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    token = access_token.strip()
    if len(token) < 30 or len(token) > 4096:
        raise HTTPException(400, "The token format does not look valid.")
    # Verify the token with Meta without returning or logging it.
    try:
        response = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/me",
            params={"fields": "id,name", "access_token": token},
            timeout=20,
        )
        data = response.json()
    except requests.RequestException:
        raise HTTPException(502, "Could not reach Meta. Try again later.")
    if not response.ok or not data.get("id"):
        raise HTTPException(400, "Meta did not accept this token. Check its validity and permissions.")
    user.encrypted_meta_token = cipher.encrypt(token.encode("utf-8")).decode("ascii")
    db.commit()
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/api/pages")
def list_pages(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        raise HTTPException(401, "Log in first.")
    if not user.encrypted_meta_token:
        raise HTTPException(400, "Connect your Meta account first.")
    try:
        token = cipher.decrypt(user.encrypted_meta_token.encode("ascii")).decode("utf-8")
        response = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/me/accounts",
            params={"fields": "id,name", "access_token": token},
            timeout=20,
        )
        data = response.json()
    except (InvalidToken, requests.RequestException):
        raise HTTPException(502, "Could not retrieve Facebook Pages.")
    if not response.ok:
        raise HTTPException(400, "Meta could not list Pages. Check Page access and app permissions.")
    return {"pages": [{"id": p.get("id"), "name": p.get("name")} for p in data.get("data", [])]}

@app.post("/refresh-pages")
def refresh_pages(request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.encrypted_meta_token:
        raise HTTPException(400, "Connect your Meta account first.")
    try:
        token = cipher.decrypt(user.encrypted_meta_token.encode("ascii")).decode("utf-8")
        response = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/me/accounts",
            params={"fields": "id,name,access_token", "access_token": token},
            timeout=20,
        )
        data = response.json()
    except (InvalidToken, requests.RequestException):
        raise HTTPException(502, "Could not retrieve Facebook Pages.")
    if not response.ok:
        raise HTTPException(400, "Meta could not list Pages. Check Page access and permissions.")
    for item in data.get("data", []):
        page_id = str(item.get("id", ""))
        page_name = str(item.get("name", "Facebook Page"))[:255]
        page_token = item.get("access_token")
        if not page_id or not page_token:
            continue
        page = db.scalar(select(ConnectedPage).where(
            ConnectedPage.user_id == user.id, ConnectedPage.page_id == page_id
        ))
        encrypted = cipher.encrypt(page_token.encode("utf-8")).decode("ascii")
        if page is None:
            db.add(ConnectedPage(user_id=user.id, page_id=page_id, name=page_name,
                encrypted_page_token=encrypted))
        else:
            page.name = page_name
            page.encrypted_page_token = encrypted
    db.commit()
    return RedirectResponse("/dashboard", status_code=303)

@app.post("/select-page")
def select_page(request: Request, page_id: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    pages = db.scalars(select(ConnectedPage).where(ConnectedPage.user_id == user.id)).all()
    match = next((p for p in pages if p.page_id == page_id), None)
    if match is None:
        raise HTTPException(404, "That Page is not connected to this account.")
    for page in pages:
        page.selected = (page.id == match.id)
    db.commit()
    return RedirectResponse("/dashboard", status_code=303)

@app.post("/upload")
async def upload_csv(request: Request, file: UploadFile = File(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        raise HTTPException(401, "Log in first.")
    if not file.filename or Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(400, "Upload a .csv file.")
    raw = await file.read(15 * 1024 * 1024 + 1)
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "CSV file is larger than 15 MB.")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fields = [str(x).strip().lower() for x in (reader.fieldnames or [])]
        if not fields or not any(x in fields for x in ("video url", "video_url")):
            raise HTTPException(400, "CSV needs a Video Url or Video URL column.")
        rows = list(reader)
    except UnicodeDecodeError:
        raise HTTPException(400, "CSV must be UTF-8 encoded.")
    user_dir = DATA_DIR / f"user_{user.id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{secrets.token_hex(16)}.csv"
    (user_dir / stored).write_bytes(raw)
    record = Upload(user_id=user.id, original_name=Path(file.filename).name[:255], stored_name=stored, rows_count=len(rows))
    db.add(record)
    db.commit()
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/health")
def health():
    return {"status": "ok", "publishing_enabled": False}
