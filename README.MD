@"
# Operação Cadê o Equipamento?

API com controle de acesso por papéis (Flask + MySQL + JWT).

## Usuários de teste (senha de todos: 123456)

| E-mail | Papel | Permissões |
|---|---|---|
| admin@escola.com | Administrador | Cadastrar/remover equipamentos, aprovar, negar e devolver empréstimos |
| gestor@escola.com | Gestor | Aprovar, negar e devolver empréstimos |
| aluno@escola.com | Comum | Ver catálogo e solicitar empréstimos |

senhas de todos os logins: 123456

As senhas ficam no banco como hash (scrypt, via Werkzeug).

## Como rodar

1. Rode o schema.sql no banco.
2. pip install -r requirements.txt
3. python app.py
4. Abra http://127.0.0.1:5000
