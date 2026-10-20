"""Operação "Cadê o Equipamento?" - API com RBAC (Flask + MySQL + JWT)."""
import os
from datetime import datetime, timedelta, timezone
from functools import wraps
 
import jwt
from flask import Flask, g, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
 
# ───────────────────────── Configuração ─────────────────────────
# Túnel SSH (o app abre sozinho ao rodar "python app.py").
# Para usar um túnel manual (ssh -L ...), defina USAR_TUNEL=0.
USAR_TUNEL = os.getenv("USAR_TUNEL", "1") == "1"
SSH_HOST = os.getenv("SSH_HOST", "10.10.230.213")
SSH_PORT = int(os.getenv("SSH_PORT", "22"))
SSH_USER = os.getenv("SSH_USER", "senac")
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "Jovem2026")
TUNEL_PORTA_LOCAL = int(os.getenv("TUNEL_PORTA_LOCAL", "3307"))
 
# Senha com "@" precisa ser escrita como %40 na URL.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"mysql+pymysql://aluno06:C%40nes2026@127.0.0.1:{TUNEL_PORTA_LOCAL}/aluno06",
)
SECRET = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
 
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 280}
db = SQLAlchemy(app)
 
COMUM, GESTOR, ADMIN = "comum", "gestor", "admin"
 
 
def agora():
    """UTC sem fuso (compatível com DATETIME do MySQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
 
 
# ───────────── Exceções de domínio → códigos HTTP semânticos ─────────────
class AppError(Exception):
    status = 500
    def __init__(self, msg=None):
        super().__init__(msg or self.__class__.__doc__)
 
class ValidationError(AppError):
    "Dados inválidos."; status = 400
class AuthenticationError(AppError):
    "Autenticação necessária ou credenciais inválidas."; status = 401
class PermissionDenied(AppError):
    "Seu papel não permite esta operação."; status = 403
class NotFound(AppError):
    "Recurso não encontrado."; status = 404
class Conflict(AppError):
    "Operação conflita com o estado atual do recurso."; status = 409
 
 
@app.errorhandler(AppError)
def handle_app_error(e):
    return jsonify(erro=e.__class__.__name__, mensagem=str(e)), e.status
 
@app.errorhandler(404)
def handle_404(_):
    return jsonify(erro="NotFound", mensagem="Rota não encontrada."), 404
 
@app.errorhandler(405)
def handle_405(_):
    return jsonify(erro="MethodNotAllowed", mensagem="Método não permitido."), 405
 
@app.errorhandler(Exception)
def handle_unexpected(e):
    db.session.rollback()
    app.logger.exception(e)
    return jsonify(erro="InternalError", mensagem="Erro interno do servidor."), 500
 
 
# ───────────────────────────── Modelos ─────────────────────────────
class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    papel = db.Column(db.Enum(COMUM, GESTOR, ADMIN), nullable=False, default=COMUM)
 
    def to_dict(self):
        return dict(id=self.id, nome=self.nome, email=self.email, papel=self.papel)
 
 
class Equipamento(db.Model):
    __tablename__ = "equipamentos"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(60), nullable=False)
    patrimonio = db.Column(db.String(40), unique=True, nullable=False)
    status = db.Column(db.Enum("disponivel", "emprestado"), nullable=False, default="disponivel")
 
    def to_dict(self):
        return dict(id=self.id, nome=self.nome, categoria=self.categoria,
                    patrimonio=self.patrimonio, status=self.status)
 
 
class Emprestimo(db.Model):
    __tablename__ = "emprestimos"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"), nullable=False)
    gestor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    status = db.Column(db.Enum("solicitado", "aprovado", "negado", "devolvido"),
                       nullable=False, default="solicitado")
    solicitado_em = db.Column(db.DateTime, default=agora)
    decidido_em = db.Column(db.DateTime)
    devolvido_em = db.Column(db.DateTime)
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])
    gestor = db.relationship("Usuario", foreign_keys=[gestor_id])
    equipamento = db.relationship("Equipamento")
 
    def to_dict(self):
        f = lambda d: d.isoformat() if d else None
        return dict(id=self.id, status=self.status,
                    usuario=self.usuario.nome, equipamento=self.equipamento.nome,
                    patrimonio=self.equipamento.patrimonio,
                    gestor=self.gestor.nome if self.gestor else None,
                    solicitado_em=f(self.solicitado_em), decidido_em=f(self.decidido_em),
                    devolvido_em=f(self.devolvido_em))
 
 
# ─────────────────────── Autenticação e RBAC ───────────────────────
def gerar_token(u):
    payload = {"sub": str(u.id), "exp": datetime.now(timezone.utc) + timedelta(hours=8)}
    return jwt.encode(payload, SECRET, algorithm="HS256")
 
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise AuthenticationError("Faça login para acessar este recurso.")
        try:
            dados = jwt.decode(header[7:], SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Sessão expirada. Entre novamente.")
        except jwt.InvalidTokenError:
            raise AuthenticationError("Token inválido.")
        g.user = db.session.get(Usuario, int(dados["sub"]))
        if not g.user:
            raise AuthenticationError("Usuário do token não existe mais.")
        return fn(*a, **kw)
    return wrapper
 
def roles_required(*papeis):
    def deco(fn):
        @wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if g.user.papel not in papeis:
                raise PermissionDenied(
                    f"Papel '{g.user.papel}' não pode executar esta ação "
                    f"(exige: {', '.join(papeis)}).")
            return fn(*a, **kw)
        return wrapper
    return deco
 
def body(*campos):
    dados = request.get_json(silent=True) or {}
    faltando = [c for c in campos if not str(dados.get(c, "")).strip()]
    if faltando:
        raise ValidationError(f"Campos obrigatórios: {', '.join(faltando)}.")
    return dados
 
def obter(model, id_):
    obj = db.session.get(model, id_)
    if not obj:
        raise NotFound(f"{model.__name__} {id_} não encontrado.")
    return obj
 
 
# ───────────────────────────── Rotas ─────────────────────────────
@app.get("/")
def index():
    return app.send_static_file("index.html")
 
@app.post("/api/auth/registro")          # público: sempre cria usuário comum
def registro():
    d = body("nome", "email", "senha")
    if Usuario.query.filter_by(email=d["email"]).first():
        raise Conflict("E-mail já cadastrado.")
    u = Usuario(nome=d["nome"], email=d["email"], papel=COMUM,
                senha_hash=generate_password_hash(d["senha"]))
    db.session.add(u); db.session.commit()
    return jsonify(u.to_dict()), 201
 
@app.post("/api/auth/login")
def login():
    d = body("email", "senha")
    u = Usuario.query.filter_by(email=d["email"]).first()
    if not u or not check_password_hash(u.senha_hash, d["senha"]):
        raise AuthenticationError("E-mail ou senha incorretos.")
    return jsonify(token=gerar_token(u), usuario=u.to_dict())
 
@app.post("/api/usuarios")               # admin cria gestores/admins
@roles_required(ADMIN)
def criar_usuario():
    d = body("nome", "email", "senha", "papel")
    if d["papel"] not in (COMUM, GESTOR, ADMIN):
        raise ValidationError("Papel inválido.")
    if Usuario.query.filter_by(email=d["email"]).first():
        raise Conflict("E-mail já cadastrado.")
    u = Usuario(nome=d["nome"], email=d["email"], papel=d["papel"],
                senha_hash=generate_password_hash(d["senha"]))
    db.session.add(u); db.session.commit()
    return jsonify(u.to_dict()), 201
 
# ── Equipamentos ──
@app.get("/api/equipamentos")
@login_required
def listar_equipamentos():
    return jsonify([e.to_dict() for e in Equipamento.query.order_by(Equipamento.nome)])
 
@app.post("/api/equipamentos")           # somente ADMIN
@roles_required(ADMIN)
def cadastrar_equipamento():
    d = body("nome", "categoria", "patrimonio")
    if Equipamento.query.filter_by(patrimonio=d["patrimonio"]).first():
        raise Conflict("Já existe equipamento com este patrimônio.")
    e = Equipamento(nome=d["nome"], categoria=d["categoria"], patrimonio=d["patrimonio"])
    db.session.add(e); db.session.commit()
    return jsonify(e.to_dict()), 201
 
@app.delete("/api/equipamentos/<int:id_>")  # somente ADMIN
@roles_required(ADMIN)
def remover_equipamento(id_):
    e = obter(Equipamento, id_)
    if e.status == "emprestado":
        raise Conflict("Equipamento emprestado não pode ser removido.")
    if Emprestimo.query.filter_by(equipamento_id=id_, status="solicitado").first():
        raise Conflict("Há solicitações pendentes para este equipamento.")
    Emprestimo.query.filter_by(equipamento_id=id_).delete()
    db.session.delete(e); db.session.commit()
    return "", 204
 
# ── Empréstimos ──
@app.get("/api/emprestimos")
@login_required
def listar_emprestimos():
    q = Emprestimo.query.order_by(Emprestimo.id.desc())
    if g.user.papel == COMUM:            # comum só enxerga os próprios
        q = q.filter_by(usuario_id=g.user.id)
    return jsonify([x.to_dict() for x in q])
 
@app.post("/api/emprestimos")            # qualquer usuário autenticado solicita
@login_required
def solicitar():
    d = body("equipamento_id")
    e = obter(Equipamento, int(d["equipamento_id"]))
    if e.status != "disponivel":
        raise Conflict("Equipamento indisponível no momento.")
    if Emprestimo.query.filter_by(usuario_id=g.user.id, equipamento_id=e.id,
                                  status="solicitado").first():
        raise Conflict("Você já solicitou este equipamento.")
    emp = Emprestimo(usuario_id=g.user.id, equipamento_id=e.id)
    db.session.add(emp); db.session.commit()
    return jsonify(emp.to_dict()), 201
 
def _decidir(id_, aprovar):
    emp = obter(Emprestimo, id_)
    if emp.status != "solicitado":
        raise Conflict(f"Empréstimo já está '{emp.status}'.")
    if aprovar:
        if emp.usuario_id == g.user.id:
            raise PermissionDenied("Você não pode aprovar o próprio pedido.")
        if emp.equipamento.status != "disponivel":
            raise Conflict("Equipamento não está mais disponível.")
        emp.equipamento.status = "emprestado"
    emp.status = "aprovado" if aprovar else "negado"
    emp.gestor_id, emp.decidido_em = g.user.id, agora()
    db.session.commit()
    return jsonify(emp.to_dict())
 
@app.post("/api/emprestimos/<int:id_>/aprovar")
@roles_required(GESTOR, ADMIN)
def aprovar(id_): return _decidir(id_, True)
 
@app.post("/api/emprestimos/<int:id_>/negar")
@roles_required(GESTOR, ADMIN)
def negar(id_): return _decidir(id_, False)
 
@app.post("/api/emprestimos/<int:id_>/devolver")
@roles_required(GESTOR, ADMIN)
def devolver(id_):
    emp = obter(Emprestimo, id_)
    if emp.status != "aprovado":
        raise Conflict("Só é possível devolver empréstimos aprovados.")
    emp.status, emp.devolvido_em = "devolvido", agora()
    emp.equipamento.status = "disponivel"
    db.session.commit()
    return jsonify(emp.to_dict())
 
 
# ───────────────────────── Inicialização ─────────────────────────
def seed():
    if Usuario.query.count():
        return
    for nome, email, papel in [("Administrador", "admin@escola.com", ADMIN),
                               ("Gestor", "gestor@escola.com", GESTOR),
                               ("Joãozinho", "aluno@escola.com", COMUM)]:
        db.session.add(Usuario(nome=nome, email=email, papel=papel,
                               senha_hash=generate_password_hash("123456")))
    db.session.commit()
 
 
def abrir_tunel():
    from sshtunnel import SSHTunnelForwarder
    tunel = SSHTunnelForwarder(
        (SSH_HOST, SSH_PORT),
        ssh_username=SSH_USER,
        ssh_password=SSH_PASSWORD,
        remote_bind_address=("127.0.0.1", 3306),
        local_bind_address=("127.0.0.1", TUNEL_PORTA_LOCAL),
    )
    tunel.start()
    print(f"[tunel] SSH aberto: 127.0.0.1:{TUNEL_PORTA_LOCAL} -> {SSH_HOST} -> MySQL:3306")
    return tunel
 
 
if __name__ == "__main__":
    tunel = abrir_tunel() if USAR_TUNEL else None
    try:
        with app.app_context():
            db.create_all()
            seed()
        # use_reloader=False: o reloader executaria o arquivo 2x e abriria o túnel 2x
        app.run(debug=True, use_reloader=False)
    finally:
        if tunel:
            tunel.stop()