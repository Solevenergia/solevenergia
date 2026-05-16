/* ─────────────────────────────────────────────────────────────────────────────
   pix-validacao.js — valida UC tem chave PIX antes de gerar cobrança.

   Uso:
     1) Inclua o partial: {% include '_modal_pix_validacao.html' %}
     2) Inclua este JS:    <script src="/static/js/pix-validacao.js"></script>
     3) Chame antes de gerar:
          validarPixAntesDeGerar(uc).then(podeGerar => {
            if (podeGerar) submitForm();
          });

   Status retornados pelo endpoint /api/validar-pix-uc/<uc>:
     - "ok"          → resolve true imediatamente
     - "sem_pix"     → modal "Usina X sem PIX cadastrado"  → cadastrar OU emitir sem QR
     - "sem_usina"   → modal "UC sem usina vinculada"      → vincular OU emitir sem QR
     - "sem_cliente" → resolve true (sem dados pra validar)
   ───────────────────────────────────────────────────────────────────────────── */

(function (global) {
  "use strict";

  /**
   * Valida se a UC tem chave PIX cadastrada antes de gerar cobrança.
   * @param {string} uc — código da UC
   * @returns {Promise<boolean>} resolve(true) se pode gerar, resolve(false) se cancelar
   */
  global.validarPixAntesDeGerar = async function (uc) {
    if (!uc) return true;
    let dados;
    try {
      const r = await fetch("/api/validar-pix-uc/" + encodeURIComponent(uc));
      if (!r.ok) return true;          // em erro, deixa seguir
      dados = await r.json();
    } catch (e) {
      return true;                      // network down, segue
    }

    if (dados.status === "ok" || dados.status === "sem_cliente") return true;

    return new Promise(function (resolve) {
      const modalEl = document.getElementById("modalPixValidacao");
      if (!modalEl) {
        // Fallback: se o template não incluiu o partial, usa confirm() nativo
        const txt = (dados.status === "sem_pix")
          ? `A usina '${dados.nome_usina || ""}' não tem chave PIX cadastrada.\n` +
            `Emitir cobrança SEM o QR Code?`
          : `Esta UC não está vinculada a nenhuma usina.\n` +
            `Emitir cobrança SEM o QR Code?`;
        resolve(confirm(txt));
        return;
      }

      const titulo  = document.getElementById("modalPixTitulo");
      const msgEl   = document.getElementById("modalPixMensagem");
      const btnSem  = document.getElementById("btnPixEmitirSemQR");
      const btnCad  = document.getElementById("btnPixCadastrar");
      const btnLbl  = document.getElementById("btnPixCadastrarLabel");
      const btnX    = modalEl.querySelector(".btn-close");
      const btnCnc  = modalEl.querySelector('[data-bs-dismiss="modal"]');

      if (dados.status === "sem_pix") {
        titulo.innerHTML = '<i class="bi bi-exclamation-triangle-fill text-warning me-2"></i>' +
                           'Usina sem chave PIX';
        msgEl.innerHTML  = `Esta UC está vinculada à usina <strong>${escapeHtml(dados.nome_usina || "(sem nome)")}</strong>, ` +
                           `porém não há <strong>chave PIX</strong> cadastrada para essa usina.`;
        btnLbl.textContent = "Cadastrar PIX da usina";
        btnCad.href        = "/usinas/editar/" + dados.id_usina;
      } else if (dados.status === "sem_usina") {
        titulo.innerHTML = '<i class="bi bi-link-45deg text-warning me-2"></i>' +
                           'UC sem usina vinculada';
        msgEl.innerHTML  = `O cliente <strong>${escapeHtml(dados.nome_cliente || "")}</strong> ` +
                           `não está vinculado a nenhuma usina geradora — ` +
                           `por isso não há recebedor PIX para gerar o QR Code.`;
        btnLbl.textContent = "Vincular usina ao cliente";
        btnCad.href        = "/clientes/editar/" + dados.id_cliente;
      }

      let resolvido = false;
      function fechar(valor) {
        if (resolvido) return;
        resolvido = true;
        try {
          const m = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
          m.hide();
        } catch (e) {}
        // Limpa listeners
        btnSem.removeEventListener("click", onSem);
        btnCad.removeEventListener("click", onCad);
        btnX  && btnX.removeEventListener("click", onCancelar);
        btnCnc&& btnCnc.removeEventListener("click", onCancelar);
        modalEl.removeEventListener("hidden.bs.modal", onHidden);
        resolve(valor);
      }
      function onSem() { fechar(true); }       // segue gerando sem QR
      function onCad() { fechar(false); }      // abre cadastro em nova aba e cancela geração
      function onCancelar() { fechar(false); }
      function onHidden()   { fechar(false); }

      btnSem.addEventListener("click", onSem);
      btnCad.addEventListener("click", onCad);
      btnX   && btnX.addEventListener("click", onCancelar);
      btnCnc && btnCnc.addEventListener("click", onCancelar);
      modalEl.addEventListener("hidden.bs.modal", onHidden);

      const m = new bootstrap.Modal(modalEl);
      m.show();
    });
  };

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
})(window);
