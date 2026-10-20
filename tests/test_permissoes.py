import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402

SENHAS = {"comum@demo.com": "comum123", "gestor@demo.com": "gestor123", "admin@demo.com": "admin123"}


class PermissoesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = create_app({"DATABASE": self.tmp.name, "TESTING": False})
        self.c = self.app.test_client()
        self.h = {k: self.login(k) for k in SENHAS}

    def tearDown(self):
        os.unlink(self.tmp.name)

    def login(self, email):
        r = self.c.post("/api/auth/login", json={"email": email, "senha": SENHAS[email]})
        self.assertEqual(r.status_code, 200)
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def cadastrar(self, patrimonio="NB-001"):
        r = self.c.post("/api/equipamentos", json={"nome": "Notebook", "patrimonio": patrimonio},
                        headers=self.h["admin@demo.com"])
        self.assertEqual(r.status_code, 201)
        return r.get_json()["id"]

    def solicitar(self, eq_id):
        r = self.c.post("/api/emprestimos", json={"equipamento_id": eq_id}, headers=self.h["comum@demo.com"])
        self.assertEqual(r.status_code, 201)
        return r.get_json()["id"]

    # --- 401 -----------------------------------------------------------
    def test_sem_token_401(self):
        for metodo, rota in [("get", "/api/equipamentos"), ("post", "/api/equipamentos"),
                             ("post", "/api/emprestimos"), ("post", "/api/emprestimos/1/aprovar")]:
            r = getattr(self.c, metodo)(rota, json={})
            self.assertEqual(r.status_code, 401, rota)
            self.assertEqual(r.get_json()["erro"]["codigo"], "nao_autenticado")

    def test_token_invalido_401(self):
        r = self.c.get("/api/me", headers={"Authorization": "Bearer lixo"})
        self.assertEqual(r.status_code, 401)

    def test_login_errado_401(self):
        r = self.c.post("/api/auth/login", json={"email": "comum@demo.com", "senha": "x"})
        self.assertEqual(r.status_code, 401)

    # --- 403: matriz de permissões ---------------------------------------
    def test_cadastro_so_administrador(self):
        corpo = {"nome": "Furadeira", "patrimonio": "FR-9"}
        self.assertEqual(self.c.post("/api/equipamentos", json=corpo, headers=self.h["comum@demo.com"]).status_code, 403)
        self.assertEqual(self.c.post("/api/equipamentos", json=corpo, headers=self.h["gestor@demo.com"]).status_code, 403)
        self.assertEqual(self.c.post("/api/equipamentos", json=corpo, headers=self.h["admin@demo.com"]).status_code, 201)

    def test_aprovar_e_devolver_so_gestor(self):
        emp = self.solicitar(self.cadastrar())
        for rota in ("aprovar", "devolver"):
            for quem in ("comum@demo.com", "admin@demo.com"):
                r = self.c.post(f"/api/emprestimos/{emp}/{rota}", headers=self.h[quem])
                self.assertEqual(r.status_code, 403, f"{quem} {rota}")
        self.assertEqual(self.c.post(f"/api/emprestimos/{emp}/aprovar", headers=self.h["gestor@demo.com"]).status_code, 200)
        self.assertEqual(self.c.post(f"/api/emprestimos/{emp}/devolver", headers=self.h["gestor@demo.com"]).status_code, 200)

    def test_solicitar_so_comum(self):
        eq = self.cadastrar()
        for quem in ("gestor@demo.com", "admin@demo.com"):
            r = self.c.post("/api/emprestimos", json={"equipamento_id": eq}, headers=self.h[quem])
            self.assertEqual(r.status_code, 403, quem)

    def test_registro_nao_escala_privilegio(self):
        r = self.c.post("/api/auth/registro", json={"nome": "Eve", "email": "eve@x.com",
                                                    "senha": "123456", "papel": "administrador"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["papel"], "comum")

    # --- 404 / 409 / 422 -------------------------------------------------
    def test_codigos_semanticos(self):
        g_, c_, a_ = (self.h[k] for k in ("gestor@demo.com", "comum@demo.com", "admin@demo.com"))
        self.assertEqual(self.c.post("/api/emprestimos/999/aprovar", headers=g_).status_code, 404)
        self.assertEqual(self.c.post("/api/emprestimos", json={"equipamento_id": 999}, headers=c_).status_code, 404)
        self.assertEqual(self.c.post("/api/equipamentos", json={"nome": ""}, headers=a_).status_code, 422)
        self.assertEqual(self.c.get("/api/rota-inexistente").status_code, 404)
        self.assertEqual(self.c.delete("/api/equipamentos", headers=a_).status_code, 405)
        self.cadastrar("DUP-1")
        r = self.c.post("/api/equipamentos", json={"nome": "Outro", "patrimonio": "dup-1"}, headers=a_)
        self.assertEqual(r.status_code, 409)

    def test_fluxo_completo_e_conflitos(self):
        eq = self.cadastrar()
        emp = self.solicitar(eq)
        g_ = self.h["gestor@demo.com"]
        self.assertEqual(self.c.post(f"/api/emprestimos/{emp}/devolver", headers=g_).status_code, 409)  # ainda não aprovado
        self.assertEqual(self.c.post(f"/api/emprestimos/{emp}/aprovar", headers=g_).status_code, 200)
        self.assertEqual(self.c.post(f"/api/emprestimos/{emp}/aprovar", headers=g_).status_code, 409)   # já aprovado
        r = self.c.post("/api/emprestimos", json={"equipamento_id": eq}, headers=self.h["comum@demo.com"])
        self.assertEqual(r.status_code, 409)                                                           # indisponível
        self.assertEqual(self.c.post(f"/api/emprestimos/{emp}/devolver", headers=g_).status_code, 200)
        self.assertEqual(self.c.post(f"/api/emprestimos/{emp}/devolver", headers=g_).status_code, 409)
        self.solicitar(eq)  # voltou a ficar disponível


if __name__ == "__main__":
    unittest.main()
