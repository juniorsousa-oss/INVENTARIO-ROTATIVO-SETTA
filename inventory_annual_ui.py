"""Interface do piloto anual compartilhado, exclusivamente com dados fictícios."""
from inventory_annual_pilot import AUDIT, FIRST, SECOND, ELIGIBLE, EXCLUDED, TEAMS, VALIDATED
import inventory_annual_rooms as room

STATE = "_annual_inventory_pilot_code_v2"


def _apply(st, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.rerun()


def _entry(st):
    join, create = st.tabs(["Acessar piloto", "Criar piloto"])
    with join:
        with st.form("ann_join", clear_on_submit=True):
            access = st.text_input("Código de acesso do piloto", type="password", max_chars=45)
            if st.form_submit_button("Entrar no piloto", type="primary"):
                def enter():
                    token = access.strip()
                    room.view(token)
                    st.session_state[STATE] = token
                _apply(st, enter)
    with create:
        st.subheader("Preparar a contagem")
        st.caption("Distribua os endereços aptos do S2. A base fictícia será congelada ao iniciar.")
        with st.form("ann_setup"):
            assignment = {a: st.selectbox(f"Dupla para {a}", TEAMS, index=i // 2, key=f"ann_assign_{a}")
                          for i, a in enumerate(ELIGIBLE)}
            locked = st.checkbox("Confirmo o bloqueio simulado do S2")
            if st.form_submit_button("Iniciar piloto", type="primary"):
                def start():
                    st.session_state[STATE] = room.create_room(assignment, locked)
                _apply(st, start)
        for address, reason in EXCLUDED.items():
            st.caption(f"{address} · Não apto: {reason}. Seu saldo de corte entra apenas na apuração final.")


def _coordinator(st, token, current):
    pilot = current["pilot"]
    st.subheader("Acompanhar endereços")
    st.caption("Saldo de corte: " + pilot.started_at.strftime("%d/%m/%Y às %H:%M"))
    st.progress(sum(pilot.address_status(a) == VALIDATED for a in ELIGIBLE) / len(ELIGIBLE))
    with st.expander("Códigos de acesso do piloto"):
        st.caption("Cada código acessa apenas um papel. Compartilhe apenas o código da função correspondente.")
        for role, secret in {room.COORD: token, **room.worker_codes(token)}.items():
            st.markdown(f"**{role}**")
            st.code(secret, language=None)
    st.subheader("Fila de pendências")
    queue = current["queue"]
    if queue:
        st.dataframe([{"Endereço": a, "Produto": c or "Todo o endereço", "Próxima ação": stage,
                       "Responsável": responsible, "Rascunho": "Salvo" if draft else "—"}
                      for a, c, stage, responsible, draft in queue], hide_index=True)
    else:
        st.success("Nenhuma pendência na fila.")
    if not pilot.closed_at:
        st.caption("O fechamento só é liberado após a entrega de todos os endereços e a conclusão das divergências.")
        if st.button("Fechar piloto e apurar", type="primary", disabled=not pilot.ready()):
            _apply(st, room.action, token, "close")
        return
    st.success("Piloto fechado. Nenhum ajuste foi enviado ao estoque ou ao Protheus.")
    st.subheader("Fechamento por produto")
    frame = [{"Código": code, "Produto": desc, "Contado (aptos)": float(counted),
              "Saldo não apto": float(excl), "Total apurado S2": float(final),
              "Saldo de corte S2": float(system), "Dif. quantidade": float(delta),
              "Dif. valor (R$)": float(value)}
             for code, desc, counted, excl, final, system, delta, value in pilot.totals()]
    short = -sum(r[-1] for r in pilot.totals() if r[-1] < 0)
    extra = sum(r[-1] for r in pilot.totals() if r[-1] > 0)
    a,b,c = st.columns(3)
    def br(value):
        return f"R$ {value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    a.metric("Faltas", br(short))
    b.metric("Sobras", br(extra))
    c.metric("Diferença líquida", br(extra - short))
    st.dataframe(frame, column_config={"Dif. valor (R$)": st.column_config.NumberColumn(format="%.2f")}, hide_index=True)
    st.subheader("Divergências e auditorias por endereço")
    details = [{"Endereço": a, "Código": code, "Saldo de corte": float(system), "1ª contagem": float(first), "2ª contagem": float(second) if second is not None else None,
                "Final": float(final),
                "Diferença": float(diff), "Decisão": decision, "Justificativa": note, "Função que auditou": auditor}
               for a, code, system, final, diff, decision, note, first, second, auditor in pilot.discrepancies()]
    if details:
        st.dataframe(details, hide_index=True)
    else:
        st.caption("Nenhuma divergência ou auditoria registrada.")
    st.info("Exportação para ajuste em massa indisponível: layout do Protheus ainda não validado.")
    evidence = []
    for key, rows in current["evidence"].items():
        stage, address, _ = key.split("|")
        for row in rows:
            evidence.append({"Etapa": stage, "Endereço": address, "Produto": row["Produto"],
                             "Lote": row["Lote"], "Quantidade": float(row["Quantidade"])})
    if evidence:
        with st.expander("Rastreio de leituras por lote"):
            st.dataframe(evidence, hide_index=True)


def _capture(st, token, stage, address, code, lines):
    st.markdown(f"**Endereço {address}**" + (f" · Produto **{code}**" if code else ""))
    st.caption("O endereço vem da tarefa; o QR atual contém produto, lote e quantidade.")
    ident = f"{stage}_{address}_{code}"
    with st.form("ann_qr_" + ident, clear_on_submit=True):
        payload = st.text_input("Ler ou colar o QR da etiqueta", max_chars=180,
                                placeholder="00000001,000101,3")
        repeat = st.checkbox("Confirmo que é outra etiqueta física, se a leitura for igual")
        if st.form_submit_button("Adicionar leitura", type="primary"):
            def register():
                item = room.parse_demo_label(payload, address)
                room.action(token, "add", stage, address, code, item=item, repeat=repeat)
            _apply(st, register)
    with st.expander("Etiqueta antiga ou lançamento manual"):
        st.caption("Leia o produto e o lote separadamente, depois informe a quantidade contada.")
        with st.form("ann_manual_" + ident, clear_on_submit=True, enter_to_submit=False):
            raw_product = st.text_input("Código do produto", max_chars=32)
            lot = st.text_input("Lote", max_chars=32)
            amount = st.text_input("Quantidade contada", max_chars=18)
            manual_repeat = st.checkbox("Confirmo que é outro volume, se o lançamento for igual")
            if st.form_submit_button("Adicionar lançamento manual"):
                def manual():
                    item = room.reading(raw_product, address, lot, amount)
                    room.action(token, "add", stage, address, code, item=item, repeat=manual_repeat)
                _apply(st, manual)
    if lines:
        st.caption(f"Rascunho salvo · {len(lines)} lançamento(s)")
        st.dataframe([dict(row, Quantidade=float(row["Quantidade"])) for row in room.grouped(lines)],
                     hide_index=True, width="stretch")
        with st.expander("Corrigir lançamento"):
            labels = {r["id"]: f"{i}. {r['product']} · lote {r['lot']} · {r['quantity']}"
                      for i, r in enumerate(lines, start=1)}
            line_id = st.selectbox("Leitura para remover", tuple(labels), format_func=labels.get,
                                   key="ann_remove_" + ident)
            if st.button("Remover leitura selecionada", key="ann_del_" + ident):
                _apply(st, room.action, token, "remove", stage, address, code, line_id=line_id)
    else:
        st.caption("Nenhuma leitura salva neste rascunho.")
    with st.form("ann_deliver_" + ident, enter_to_submit=False):
        empty = st.checkbox("Endereço conferido e vazio" if stage == FIRST else "Produto não encontrado")
        complete = st.checkbox("Conferi toda a tarefa")
        note = st.text_area("Justificativa da auditoria", max_chars=400) if stage == AUDIT else ""
        if st.form_submit_button({FIRST:"Entregar endereço", SECOND:"Confirmar 2ª contagem",
                                  AUDIT:"Validar auditoria"}[stage]):
            _apply(st, room.action, token, "submit", stage, address, code,
                   empty=empty, complete=complete, note=note)


def _worker(st, token, current):
    if current["closed"]:
        st.info("Piloto encerrado. Consulte a Coordenação.")
        return
    tasksets = current["tasks"]
    if current["role"] == room.AUDITOR:
        stage = AUDIT
    else:
        stage = st.radio("Etapa da dupla", (FIRST, SECOND), horizontal=True,
                         format_func=lambda value: value + " cega", key="ann_stage")
    tasks = tasksets.get(stage, [])
    st.subheader(stage + (" cega" if stage != AUDIT else ""))
    if not tasks:
        if stage == FIRST:
            st.session_state.pop("_ann_active_first", None)
        st.info("Nenhuma tarefa pendente nesta etapa.")
        return
    if stage == FIRST:
        active = st.session_state.get("_ann_active_first")
        allowed = [a for a, _ in tasks]
        if active not in allowed:
            st.session_state.pop("_ann_active_first", None)
            option = st.selectbox("Endereço da sua dupla", allowed, index=None,
                                  placeholder="Selecione o endereço para contar")
            if st.button("Abrir endereço", type="primary", disabled=option is None):
                st.session_state["_ann_active_first"] = option
                st.rerun()
            st.caption("Abra um endereço por vez. Depois de fechar, escolha o próximo da sua dupla.")
            return
        address, code = active, ""
        if st.button("Voltar aos endereços"):
            st.session_state.pop("_ann_active_first", None)
            st.rerun()
    else:
        address, code = st.selectbox(
            {SECOND:"Posição para recontar", AUDIT:"Posição para auditoria"}[stage],
            tasks, format_func=lambda pair: " · ".join(pair), key="ann_task_" + stage)
    _capture(st, token, stage, address, code, current["drafts"][room._key(stage, address, code)])


def render(st):
    st.warning("PILOTO · Dados fictícios do S2. Sem integração com o estoque real ou o Protheus.")
    st.caption("Use códigos individuais para testar em aparelhos separados. Os rascunhos salvos ficam neste piloto por até três dias e dependem de o servidor não ser recriado.")
    token = st.session_state.get(STATE)
    if not token:
        _entry(st)
        return
    try:
        current = room.view(token)
    except ValueError as exc:
        st.session_state.pop(STATE, None)
        st.warning(str(exc))
        _entry(st)
        return
    left, right = st.columns([3, 2])
    left.markdown("**Acesso:** " + current["role"])
    if right.button("Sair do piloto"):
        st.session_state.pop(STATE, None)
        st.session_state.pop("_ann_active_first", None)
        st.rerun()
    st.button("Atualizar fila", key="ann_update", help="Busca alterações salvas pelas outras duplas.")
    if current["role"] == room.COORD:
        _coordinator(st, token, current)
    else:
        _worker(st, token, current)
