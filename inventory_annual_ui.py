"""Interface do piloto anual compartilhado, exclusivamente com dados fictícios."""
from inventory_annual_pilot import AUDIT, FIRST, SECOND, ELIGIBLE, VALIDATED
import inventory_annual_rooms as room

STATE = "_annual_inventory_pilot_code_v2"
MEMBERSHIPS = "_annual_memberships_v3"
OPEN = "_annual_open_team_v3"
PREP = "_annual_prepare_teams_v3"


def _apply(st, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.rerun()


def _add_code(st, manager):
    with st.form("ann_join", clear_on_submit=True):
        access = st.text_input("Código de acesso do piloto", type="password", max_chars=45)
        if st.form_submit_button("Entrar no piloto", type="primary"):
            def enter():
                token = access.strip()
                profile = room.view(token)
                if profile["role"] == room.COORD and not manager:
                    raise ValueError("A Coordenação exige login de Gestor no Inventário.")
                if profile["role"] != room.COORD:
                    codes = st.session_state.setdefault(MEMBERSHIPS, [])
                    if token not in codes:
                        codes.append(token)
                st.session_state[STATE] = token
                st.session_state.pop(OPEN, None)
            _apply(st, enter)


def _setup(st):
    st.subheader("Preparar a contagem")
    st.caption("Use nomes fictícios. O saldo simulado do S2 é congelado ao iniciar.")
    plan = st.session_state.get(PREP) or {}
    if not plan.get("ready"):
        with st.form("ann_setup_free", enter_to_submit=False):
            title = st.text_input("Nome do inventário", value=plan.get("title", room.TITLE), max_chars=60)
            mode = st.radio("Como será a contagem?", (room.INDIVIDUAL, room.PAIRS),
                            index=0 if plan.get("mode") == room.INDIVIDUAL else 1, horizontal=True)
            people = st.number_input("Quantas pessoas vão realizar a contagem?", min_value=1,
                                     value=plan.get("people"), step=1, placeholder="Informe o total de pessoas")
            participants = st.text_area("Participantes, um por linha", value=plan.get("participants", ""),
                        help="Em duplas, informe o cabeça de chave e depois o auxiliar de cada dupla. "
                             "Se sobrar uma pessoa, ela conta individualmente.")
            if st.form_submit_button("Conferir formação", type="primary"):
                def confirm_teams():
                    valid = room.formation(people, mode, participants, title)
                    st.session_state[PREP] = {**valid, "people": people, "participants": participants, "ready": True}
                _apply(st, confirm_teams)
        return
    st.subheader("Equipes formadas")
    st.caption(f'{plan["people"]} pessoa(s) · {len(plan["teams"])} equipe(s) · {plan["mode"]}')
    st.dataframe([{"Equipe": d["name"], "Responsável": d["lead"],
                   "Auxiliar": d["assistant"] or "—"} for d in plan["teams"].values()], hide_index=True)
    st.caption("Sem endereços pré-atribuídos. Cada equipe informa um endereço apto do S2; o piloto confere o cadastro antes de abrir.")
    if st.button("Editar formação das equipes"):
        st.session_state[PREP] = {**plan, "ready": False}
        st.rerun()
    with st.form("ann_start_free", enter_to_submit=False):
        locked = st.checkbox("Confirmo o bloqueio simulado do S2")
        if st.form_submit_button("Iniciar piloto", type="primary"):
            def start():
                st.session_state[STATE] = room.create_room({}, locked, people=plan["people"], title=plan["title"],
                    mode=plan["mode"], participants=plan["participants"])
                st.session_state.pop(PREP, None)
            _apply(st, start)


def _entry(st, manager):
    if not manager:
        _add_code(st, manager=False)
        return
    join, create = st.tabs(["Acessar piloto", "Criar piloto"])
    with join:
        _add_code(st, manager=True)
    with create:
        _setup(st)


def _coordinator(st, token, current):
    pilot = current["pilot"]
    st.subheader("Acompanhar endereços")
    st.text(current["title"])
    st.caption("Saldo de corte: " + pilot.started_at.strftime("%d/%m/%Y às %H:%M"))
    covered = set(pilot.eligible_addresses()) | pilot.assignment.keys()
    st.progress(sum(pilot.address_status(a) == VALIDATED for a in covered) / len(covered))
    with st.expander("Equipes e endereços"):
        st.dataframe([{"Equipe": data["name"], "Cabeça de chave": data["lead"], "Auxiliar": data["assistant"],
                       "Endereços": ", ".join(a for a, owner in sorted(pilot.assignment.items()) if owner == idx) or "—"}
                      for idx, data in current["teams"].items()], hide_index=True)
    with st.expander("Códigos de acesso do piloto"):
        st.caption("Cada código acessa apenas um papel. Compartilhe apenas o código da função correspondente.")
        for role, secret in {room.COORD: token, **room.worker_codes(token, pilot.teams)}.items():
            st.text(current["teams"].get(role, {}).get("name", role))
            st.code(secret, language=None)
    st.subheader("Fila de pendências")
    queue = current["queue"]
    if queue:
        st.dataframe([{"Endereço": a, "Produto": c or "Todo o endereço", "Próxima ação": stage,
                       "Responsável": current["teams"].get(responsible, {}).get("name", responsible), "Rascunho": "Salvo" if draft else "—"}
                      for a, c, stage, responsible, draft in queue], hide_index=True)
    else:
        st.success("Nenhuma pendência na fila.")
    if current["extras"]:
        with st.expander("Conferências extras • fora do total"):
            st.dataframe([{"Endereço": a, "Equipe": current["teams"][t]["name"],
                           "Situação": "Enviada" if status == "submitted" else "Em contagem"}
                           for a, t, status, _ in current["extras"]], hide_index=True)
            details = [{"Endereço": a, "Equipe": current["teams"][t]["name"],
                        **dict(row, Quantidade=float(row["Quantidade"]))}
                       for a, t, status, rows in current["extras"] if status == "submitted" for row in rows]
            if details:
                st.dataframe(details, hide_index=True)
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
    if pilot.tracked:
        st.subheader("Conferência por lote")
        lot_rows = [{"Endereço": a, "Produto": code, "Lote": lot, "Saldo de corte": float(system),
                     "1ª contagem": float(first), "2ª contagem": float(second) if second is not None else None,
                     "Final": float(final), "Diferença final": float(delta)}
                    for a, code, lot, system, first, second, final, delta in pilot.lot_discrepancies()]
        if lot_rows:
            st.dataframe(lot_rows, hide_index=True)
        else:
            st.caption("Nenhuma diferença registrada nos lotes rastreados.")
        st.caption("O ajuste em valor continua por produto. Uma troca de lotes com totais iguais não gera diferença em reais.")
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
            selected = next(row for row in lines if row["id"] == line_id)
            with st.form("ann_edit_" + ident + line_id, enter_to_submit=False):
                updated_product = st.text_input("Produto do lançamento", value=selected["product"], max_chars=32,
                                                disabled=bool(code))
                updated_lot = st.text_input("Lote do lançamento", value=selected["lot"], max_chars=32)
                updated_qty = st.text_input("Quantidade do lançamento", value=selected["quantity"], max_chars=18)
                if st.form_submit_button("Salvar edição"):
                    def edit():
                        item = room.reading(updated_product, address, updated_lot, updated_qty, selected["label_id"])
                        room.action(token, "edit", stage, address, code, item=item, line_id=line_id, expected=selected)
                    _apply(st, edit)
            if st.button("Remover leitura selecionada", key="ann_del_" + ident):
                _apply(st, room.action, token, "remove", stage, address, code, line_id=line_id, expected=selected)
    else:
        st.caption("Nenhuma leitura salva neste rascunho.")
    with st.form("ann_deliver_" + ident, enter_to_submit=False):
        empty = st.checkbox("Endereço conferido e vazio" if stage in (FIRST, room.EXTRA) else "Produto não encontrado")
        complete = st.checkbox("Conferi os lançamentos e confirmo o envio" if stage == FIRST else "Conferi toda a tarefa")
        if stage == FIRST:
            st.caption("Só o envio fecha a contagem para conferência e impede novas edições.")
        note = st.text_area("Justificativa da auditoria", max_chars=400) if stage == AUDIT else ""
        if st.form_submit_button({FIRST:"Enviar para conferência", SECOND:"Confirmar 2ª contagem",
                                  AUDIT:"Validar auditoria", room.EXTRA:"Enviar conferência extra"}[stage]):
            def submit():
                room.action(token, "submit", stage, address, code,
                            empty=empty, complete=complete, note=note, expected=room.draft_version(lines))
                if stage == FIRST:
                    st.session_state["_annual_last_sent_v3"] = (token, address)
                if stage in (FIRST, room.EXTRA):
                    st.session_state.pop("_annual_free_active", None)
                if stage == room.EXTRA:
                    st.session_state["_annual_extra_sent"] = (token, address)
            _apply(st, submit)


def _free_count(st, token, current):
    active = st.session_state.get("_annual_free_active")
    if active and active[0] == token:
        _, stage, address = active
        key = room.task_key(stage, address, "", current["role"])
        if key in current["drafts"]:
            if st.button("Sair do endereço sem enviar"):
                st.session_state.pop("_annual_free_active", None)
                st.rerun()
            if stage == room.EXTRA:
                st.info("Conferência extra. Esta contagem não substitui nem soma com a oficial.")
            _capture(st, token, stage, address, "", current["drafts"][key])
            return
    sent = st.session_state.get("_annual_last_sent_v3")
    if sent and sent[0] == token:
        st.success(f"{sent[1]} enviado para conferência.")
    extra_sent = st.session_state.get("_annual_extra_sent")
    if extra_sent and extra_sent[0] == token:
        st.success(f"{extra_sent[1]}: conferência extra enviada. Ela não entra no total.")

    def open_at(raw, owner=""):
        try:
            address = room.normalize_address(raw)
            stage, address = room.action(token, "open", address=address, confirm_owner=owner)
        except room.AddressConflict as exc:
            st.session_state["_annual_address_conflict"] = (token, address, exc.owner, str(exc))
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["_annual_free_active"] = (token, stage, address)
            for key in ("_annual_address_conflict", "_annual_last_sent_v3", "_annual_extra_sent"):
                st.session_state.pop(key, None)
            st.rerun()

    options = current["address_options"]
    if options:
        address = st.selectbox("Buscar endereço do S2", options, index=None, filter_mode="contains",
                               placeholder="Digite parte do endereço", accept_new_options=False,
                               key="ann_search_" + current["room_id"])
        st.caption("A busca lista só endereços aptos do S2 do relatório ENDEREÇO. Se não aparecer, o endereço não pode ser aberto neste piloto.")
        if st.button("Abrir endereço", type="primary", disabled=address is None):
            open_at(address)
    else:
        with st.form("ann_enter_address", clear_on_submit=True):
            address = st.text_input("Informe o endereço do S2", max_chars=60)
            if st.form_submit_button("Abrir endereço", type="primary"):
                open_at(address)
    conflict = st.session_state.get("_annual_address_conflict")
    if conflict and conflict[0] == token:
        _, address, owner, message = conflict
        st.warning(f"{address}: {message}")
        st.caption("Prossiga só se a repetição for intencional. A conferência extra não entra no total oficial.")
        if st.button("Confirmar conferência extra"):
            open_at(address, owner)
        if st.button("Cancelar e escolher outro endereço"):
            st.session_state.pop("_annual_address_conflict", None)
            st.rerun()
    saved = [(stage, a) for stage in (FIRST, room.EXTRA) for a, _ in current["tasks"].get(stage, [])]
    if saved:
        st.markdown("**Meus endereços em rascunho**")
        for stage, a in saved:
            if st.button(f"Retomar {a}" + (" · Extra" if stage == room.EXTRA else ""),
                         key=f"ann_resume_{stage}_{a}"):
                open_at(a)


def _worker_stage(st, token, current, stage):
    if stage == FIRST and current["free"]:
        _free_count(st, token, current)
        return
    tasks = current["tasks"].get(stage, [])
    sent = st.session_state.get("_annual_last_sent_v3")
    if stage == FIRST and sent and sent[0] == token:
        st.success(f"{sent[1]} enviado para conferência.")
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
            option = st.selectbox("Endereço da sua equipe", allowed, index=None,
                                  placeholder="Selecione o endereço para contar")
            if st.button("Abrir endereço", type="primary", disabled=option is None):
                st.session_state["_ann_active_first"] = option
                st.session_state.pop("_annual_last_sent_v3", None)
                st.rerun()
            st.caption("Abra um endereço por vez. Você pode sair e voltar sem entregar a contagem.")
            return
        address, code = active, ""
        if st.button("Sair do endereço sem enviar"):
            st.session_state.pop("_ann_active_first", None)
            st.rerun()
    elif stage == SECOND:
        addresses = sorted({a for a, _ in tasks})
        address = st.selectbox("Endereço para recontar", addresses,
                               format_func=lambda a: f"{a} · {sum(x == a for x, _ in tasks)} produto(s)")
        products = [c for a, c in tasks if a == address]
        code = st.selectbox("Produto pendente de recontagem", products, key="ann_second_code_" + address)
        st.caption("A recontagem é cega: não são exibidos o saldo de corte nem a contagem anterior.")
    else:
        address, code = st.selectbox("Posição para auditoria", tasks,
            format_func=lambda pair: " · ".join(pair), key="ann_audit_task")
    _capture(st, token, stage, address, code, current["drafts"][room.task_key(stage, address, code, current["role"])])


def _worker(st, token, current):
    if current["closed"]:
        st.info("Inventário encerrado. Consulte a Coordenação.")
        return
    tasksets = current["tasks"]
    if FIRST in tasksets:
        first, second = st.tabs(["Contagem", "Recontagem"])
        with first:
            _worker_stage(st, token, current, FIRST)
        with second:
            _worker_stage(st, token, current, SECOND)
    elif SECOND in tasksets:
        st.subheader("Recontagem")
        _worker_stage(st, token, current, SECOND)
    else:
        st.subheader("Auditoria")
        _worker_stage(st, token, current, AUDIT)


def _inventory_list(st, manager):
    st.subheader("Meus inventários")
    codes = list(st.session_state.get(MEMBERSHIPS, []))
    for token in codes:
        try:
            current = room.view(token)
        except ValueError:
            st.session_state[MEMBERSHIPS].remove(token)
            continue
        with st.container(border=True):
            st.text(current["display"])
            st.text(current["title"])
            st.caption("Encerrado" if current["closed"] else "Em andamento")
            if st.button("Abrir inventário da equipe", key="annual_open_" + current["room_id"] + "_" + current["role"]):
                if st.session_state.get(STATE) != token:
                    st.session_state.pop("_ann_active_first", None)
                st.session_state[STATE] = token
                st.session_state[OPEN] = token
                st.rerun()
    with st.expander("Acessar outro inventário"):
        _add_code(st, manager)


def render(st, *, manager=False):
    st.warning("PILOTO · Dados fictícios do S2. Sem integração com o estoque real ou o Protheus.")
    st.caption("Novos pilotos sugerem endereços aptos do S2 com base no relatório ENDEREÇO de teste.")
    st.caption("Os rascunhos salvos ficam neste piloto por até três dias e dependem de o servidor não ser recriado.")
    token = st.session_state.get(STATE)
    if not token:
        _entry(st, manager)
        return
    try:
        current = room.view(token)
    except ValueError as exc:
        st.session_state.pop(STATE, None)
        st.warning(str(exc))
        _entry(st, manager)
        return
    if current["role"] == room.COORD and not manager:
        st.session_state.pop(STATE, None)
        st.warning("A Coordenação exige login de Gestor no Inventário.")
        _entry(st, False)
        return
    if st.button("Sair do piloto"):
        for key in (STATE, OPEN, MEMBERSHIPS, "_ann_active_first", "_annual_last_sent_v3", "_annual_free_active", "_annual_address_conflict", "_annual_extra_sent"):
            st.session_state.pop(key, None)
        st.rerun()
    if current["role"] != room.COORD and st.session_state.get(OPEN) != token:
        codes = st.session_state.setdefault(MEMBERSHIPS, [])
        if token not in codes:
            codes.append(token)
        _inventory_list(st, manager)
        return
    st.text("Acesso: " + current["display"])
    if current["role"] != room.COORD:
        st.caption(current["title"])
        if st.button("Voltar aos meus inventários"):
            st.session_state.pop(OPEN, None)
            st.session_state.pop("_ann_active_first", None)
            st.rerun()
    st.button("Atualizar fila", key="ann_update", help="Busca alterações salvas pelas outras duplas.")
    if current["role"] == room.COORD:
        _coordinator(st, token, current)
    else:
        _worker(st, token, current)
