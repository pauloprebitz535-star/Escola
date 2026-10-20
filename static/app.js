let token = localStorage.getItem("token");
let usuario = JSON.parse(localStorage.getItem("usuario") || "null");
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const podeGerir = () => ["gestor", "admin"].includes(usuario.papel);

function aviso(msg, tipo = "ok") {
  const a = $("aviso"); a.textContent = msg; a.className = tipo; a.hidden = false;
  clearTimeout(aviso.t); aviso.t = setTimeout(() => (a.hidden = true), 4500);
}

async function api(rota, metodo = "GET", corpo) {
  const r = await fetch("/api" + rota, {
    method: metodo,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  if (r.status === 204) return null;
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401 && token) sair();           // sessão inválida
    throw new Error(`${r.status} - ${dados.mensagem || "Erro inesperado"}`);
  }
  return dados;
}
const tentar = (fn) => async (...a) => { try { await fn(...a); } catch (e) { aviso(e.message, "erro"); } };

function entrar(dados) {
  token = dados.token; usuario = dados.usuario;
  localStorage.setItem("token", token); localStorage.setItem("usuario", JSON.stringify(usuario));
  render();
}
function sair() {
  token = usuario = null; localStorage.clear(); render();
}

async function render() {
  const logado = !!token && !!usuario;
  $("login-view").hidden = logado; $("app-view").hidden = !logado; $("sessao").hidden = !logado;
  if (!logado) return;
  $("quem").textContent = `${usuario.nome} (${usuario.papel})`;
  // Apenas conveniência visual: a barreira real está no servidor.
  $("cad-equip").hidden = usuario.papel !== "admin";
  $("titulo-emp").textContent = podeGerir() ? "Empréstimos" : "Meus empréstimos";
  await Promise.all([carregarEquip(), carregarEmp()]).catch((e) => aviso(e.message, "erro"));
}

async function carregarEquip() {
  const lista = await api("/equipamentos");
  $("t-equip").innerHTML = lista.map((e) => `
    <tr><td>${esc(e.patrimonio)}</td><td>${esc(e.nome)}</td><td>${esc(e.categoria)}</td>
    <td><span class="tag ${e.status}">${e.status}</span></td>
    <td>${e.status === "disponivel" ? `<button data-acao="solicitar" data-id="${e.id}">Solicitar</button>` : ""}
    ${usuario.papel === "admin" ? `<button class="no" data-acao="remover" data-id="${e.id}">Remover</button>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="5">Nenhum equipamento cadastrado.</td></tr>`;
}

async function carregarEmp() {
  const lista = await api("/emprestimos");
  $("t-emp").innerHTML = lista.map((x) => `
    <tr><td>${x.id}</td><td>${esc(x.equipamento)} <small>(${esc(x.patrimonio)})</small></td><td>${esc(x.usuario)}</td>
    <td><span class="tag ${x.status}">${x.status}</span></td>
    <td>${podeGerir() && x.status === "solicitado" ? `<button class="ok" data-acao="aprovar" data-id="${x.id}">Aprovar</button><button class="no" data-acao="negar" data-id="${x.id}">Negar</button>` : ""}
    ${podeGerir() && x.status === "aprovado" ? `<button data-acao="devolver" data-id="${x.id}">Registrar devolução</button>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="5">Nenhum empréstimo por aqui ainda.</td></tr>`;
}

document.addEventListener("click", tentar(async (ev) => {
  const b = ev.target.closest("button[data-acao]"); if (!b) return;
  const { acao, id } = b.dataset;
  if (acao === "solicitar") await api("/emprestimos", "POST", { equipamento_id: +id });
  else if (acao === "remover") await api(`/equipamentos/${id}`, "DELETE");
  else await api(`/emprestimos/${id}/${acao}`, "POST");
  aviso("Operação concluída."); await render();
}));

$("btn-login").onclick = tentar(async () =>
  entrar(await api("/auth/login", "POST", { email: $("l-email").value, senha: $("l-senha").value })));
$("btn-reg").onclick = tentar(async () => {
  await api("/auth/registro", "POST", { nome: $("r-nome").value, email: $("r-email").value, senha: $("r-senha").value });
  aviso("Conta criada. Agora é só entrar.");
});
$("btn-equip").onclick = tentar(async () => {
  await api("/equipamentos", "POST", { nome: $("e-nome").value, categoria: $("e-cat").value, patrimonio: $("e-pat").value });
  ["e-nome", "e-cat", "e-pat"].forEach((i) => ($(i).value = ""));
  aviso("Equipamento cadastrado."); await render();
});
$("sair").onclick = sair;
render();
