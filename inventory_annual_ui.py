"""Interface do piloto anual compartilhado, exclusivamente com dados fictícios."""
from hashlib import sha256

from inventory_annual_camera import scan_qr
from inventory_annual_pilot import AUDIT, FIRST, SECOND, ELIGIBLE, VALIDATED
import inventory_annual_rooms as room

STATE = "_annual_inventory_pilot_code_v2"
PREP = "_annual_prepare_teams_v3"


def _apply(st, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.rerun()


def _exchange_auxiliary(st, plan):
    teams = plan["teams"]
    origins = [key for key, team in teams.items() if team["assistant"]]
    if len(teams) < 2 or not origins:
        return
    rev = plan.get("revision", 0)
    with st.expander("Trocar auxiliar de equipe"):
        left, right = st.columns(2)
        source = left.selectbox("Auxiliar", origins, index=None, placeholder="Selecione o auxiliar",
                                format_func=lambda key: teams[key]["assistant"], key=f"ann_exchange_from_{rev}")
        targets = [key for key in teams if key != source]
        destination = right.selectbox("Novo principal", targets, index=None, placeholder="Selecione o principal",
                                      format_func=lambda key: teams[key]["lead"], key=f"ann_exchange_to_{rev}_{source}",
                                      disabled=source is None)
        if destination and teams[destination]["assistant"]:
            st.caption(f'Os auxiliares {teams[source]["assistant"]} e {teams[destination]["assistant"]} trocarão de equipe.')
        if st.button("Aplicar troca", disabled=not destination, key=f"ann_exchange_apply_{rev}"):
            def exchange():
                updated = room.move_auxiliary(teams, source, destination)
                st.session_state[PREP] = {**plan, "teams": updated,
                                         "assignments": {k: row["assistant"] for k, row in updated.items()},
                                         "revision": rev + 1}
            _apply(st, exchange)


def _setup(st):
    st.subheader("Preparar a contagem")
    plan = st.session_state.get(PREP) or {}
    if not plan.get("ready"):
        modes = (room.INDIVIDUAL, room.PAIRS, room.MIXED)
        mode = st.radio("Como será a contagem?", modes,
                        index=modes.index(plan["mode"]) if plan.get("mode") in modes else 1, horizontal=True)
        people = st.number_input("Quantas pessoas vão realizar a contagem?", min_value=1,
                                 value=plan.get("people"), step=1, placeholder="Informe o total de pessoas")
        with st.form("ann_setup_free", enter_to_submit=False):
            title = st.text_input("Nome do inventário", value=plan.get("title", room.TITLE), max_chars=60)
            saved = plan.get("participants")
            if mode == room.MIXED:
                if people:
                    rows = saved if isinstance(saved, list) else []
                    participants = st.data_editor(
                        (rows[:people] + [{"Participante": "", "Classe": room.PRINCIPAL}
                                          for _ in range(max(people - len(rows), 0))]),
                        column_config={
                            "Participante": st.column_config.TextColumn("Participante (nome fictício)", required=True, max_chars=60),
                            "Classe": st.column_config.SelectboxColumn(
                                "Classe", options=[room.PRINCIPAL, room.ASSISTANT],
                                required=True, default=room.PRINCIPAL),
                        },
                        width="stretch", hide_index=True, num_rows="fixed",
                        key=f'ann_mixed_{people}_{plan.get("revision", 0)}',
                    )
                else:
                    participants = []
            else:
                participants = st.text_area("Participantes fictícios, um por linha", value=saved if isinstance(saved, str) else "",
                            help="Em duplas, informe o principal e depois o auxiliar. A última pessoa pode contar sozinha.")
            if st.form_submit_button("Conferir formação", type="primary"):
                def confirm_teams():
                    valid = room.formation(people, mode, participants, title)
                    st.session_state[PREP] = {**valid, "people": people, "participants": participants,
                                             "ready": True, "revision": plan.get("revision", 0) + 1}
                _apply(st, confirm_teams)
        return
    st.subheader("Equipes formadas")
    st.caption(f'{plan["people"]} pessoa(s) · {len(plan["teams"])} equipe(s) · {plan["mode"]}')
    st.dataframe([{"Equipe": d["name"], "Principal": d["lead"],
                   "Auxiliar": d["assistant"] or "—"} for d in plan["teams"].values()], hide_index=True)
    _exchange_auxiliary(st, plan)
    if st.button("Editar formação das equipes"):
        st.session_state[PREP] = {**plan, "ready": False}
        st.rerun()
    if st.button("Iniciar piloto", type="primary"):
        def start():
            # Congela apenas a base fictícia da sala; não bloqueia o estoque real.
            token = room.create_room({}, True, people=plan["people"], title=plan["title"],
                mode=plan["mode"], participants=plan["participants"], assignments=plan.get("assignments"))
            st.session_state[STATE] = room.RoomAccess(room.view(token)["room_id"], room.COORD, True)
            st.session_state.pop(PREP, None)
        _apply(st, start)


def _coordinator(st, token, current):
    pilot = current["pilot"]
    closed = bool(pilot.closed_at)
    st.subheader(current["title"])
    if closed:
        status = "Encerrado"
    elif not pilot.free:
        status = "Em contagem"
    else:
        status = "Liberado para equipes" if current["visible"] else "Somente gestão"
    st.caption(status)

    options = ["Resultado" if closed else "Andamento", "Equipes", "Gerenciar"]
    section = st.segmented_control("Visão do gestor", options, default=options[0], required=True,
                                   label_visibility="collapsed", key=f'ann_coord_{"closed" if closed else "open"}_{current["room_id"]}')
    if section == "Gerenciar":
        _coordinator_management(st, token, current)
        return
    if section == "Equipes":
        _coordinator_teams(st, current)
        return
    if closed:
        _coordinator_result(st, current)
        return

    covered = set(pilot.eligible_addresses()) | pilot.assignment.keys()
    validated = sum(pilot.address_status(a) == VALIDATED for a in covered)
    st.progress(validated / len(covered) if covered else 0,
                text=f"{validated} de {len(covered)} endereços validados")
    if pilot.free and not current["visible"]:
        st.caption("O piloto só aparece para as equipes após a liberação. A visão padrão não exige login.")
        if st.button("Liberar para equipes", type="primary"):
            _apply(st, room.action, token, "publish")

    st.subheader("Pendências")
    queue = current["queue"]
    reviews = [row for row in queue if row[2] in (SECOND, AUDIT)]
    firsts = [row for row in queue if row[2] == FIRST]
    if queue:
        labels = [f"Recontagem e auditoria ({len(reviews)})", f"Primeira contagem ({len(firsts)})"]
        # Keys are stable even as counts change on refresh.
        active = st.selectbox("Etapa da fila", ["review", "first"], index=0 if reviews else 1,
                              format_func=lambda stage: labels[0 if stage == "review" else 1],
                              label_visibility="collapsed", key=f'ann_queue_filter_{current["room_id"]}')
        rows = reviews if active == "review" else firsts
        if rows:
            any_saved = any(row[-1] for row in rows)
            frame = []
            for address, code, stage, responsible, draft in rows:
                row = {"Endereço": address, "Responsável": current["teams"].get(responsible, {}).get("name", responsible)}
                if active == "review":
                    row.update({"Produto": code, "Etapa": "Auditoria" if stage == AUDIT else "Recontagem"})
                if any_saved:
                    row["Rascunho"] = "Salvo" if draft else "—"
                frame.append(row)
            st.dataframe(frame, hide_index=True, height=min(320, 39 + 35 * len(frame)))
        else:
            st.caption("Nenhuma pendência nesta etapa.")
        if active == "review" and any(row[2] == AUDIT for row in reviews) and st.button("Abrir auditoria"):
            _select(st, room.RoomAccess(current["room_id"], room.AUDITOR, True))
    else:
        st.success("Nenhuma pendência na fila.")
        if pilot.ready() and st.button("Fechar piloto e apurar", type="primary"):
            _apply(st, room.action, token, "close")
    st.button("Atualizar fila", key="ann_update", help="Busca alterações salvas pelas outras equipes.")


def _coordinator_teams(st, current):
    pilot = current["pilot"]
    st.subheader("Equipes e endereços")
    st.dataframe([{"Equipe": data["name"], "Principal": data["lead"], "Auxiliar": data["assistant"],
                   "Endereços": ", ".join(a for a, owner in sorted(pilot.assignment.items()) if owner == idx) or "—"}
                  for idx, data in current["teams"].items()], hide_index=True)
    if current["extras"]:
        with st.expander("Conferências extras • fora do total"):
            st.dataframe([{"Endereço": a, "Equipe": current["teams"][t]["name"],
                           "Situação": "Enviada" if status == "submitted" else "Em contagem"}
                          for a, t, status, _ in current["extras"]], hide_index=True)
            details = [{"Endereço": a, "Equipe": current["teams"][t]["name"],
                        **dict(row, Descrição=current["catalog"].get(row["Produto"], ""), Quantidade=float(row["Quantidade"]))}
                       for a, t, status, rows in current["extras"] if status == "submitted" for row in rows]
            if details:
                st.dataframe(details, hide_index=True)


def _coordinator_management(st, token, current):
    pilot = current["pilot"]
    st.caption("Saldo de corte: " + pilot.started_at.strftime("%d/%m/%Y às %H:%M"))
    if pilot.free:
        if not pilot.closed_at and current["visible"] and st.button("Retirar da visão padrão"):
            _apply(st, room.action, token, "hide")
        with st.expander("Cópia de segurança"):
            if st.button("Preparar cópia", key="annual_prepare_backup"):
                try:
                    data = room.backup_room(token)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.download_button(
                        "Baixar cópia do piloto", data=data,
                        file_name=f'inventario-anual-{current["room_id"]}.json',
                        mime="application/json", on_click="ignore", key="annual_download_backup",
                    )


def _coordinator_result(st, current):
    pilot = current["pilot"]
    st.success("Piloto encerrado.")
    st.subheader("Fechamento por produto")
    frame = [{"Código": code, "Produto": desc, "Contado (aptos)": float(counted),
              "Saldo não apto": float(excl), "Total apurado": float(final),
              "Saldo de estoque no corte": float(system), "Dif. quantidade": float(delta),
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
    st.caption("Exportação Protheus ainda indisponível.")
    evidence = []
    for key, rows in current["evidence"].items():
        stage, address, _ = key.split("|")
        for row in rows:
            evidence.append({"Etapa": stage, "Endereço": address, "Produto": row["Produto"],
                             "Lote": row["Lote"], "Quantidade": float(row["Quantidade"])})
    if evidence:
        with st.expander("Rastreio de leituras por lote"):
            st.dataframe(evidence, hide_index=True)


def _camera_capture(st, token, stage, address, code, ident, catalog):
    scope = sha256(f"{token}:{ident}".encode()).hexdigest()[:24]
    state_key = "_annual_camera_preview"
    preview = st.session_state.get(state_key)
    payload = preview[1] if preview and preview[0] == scope else None
    if payload is None:
        payload = scan_qr("ann_cam_" + scope)
        if payload is None:
            return
        st.session_state[state_key] = (scope, payload)
        st.rerun()
    try:
        item = room.parse_demo_label(payload, address, catalog=catalog)
        if code and item.product != code:
            raise ValueError("A etiqueta não pertence ao produto desta tarefa.")
    except ValueError as exc:
        st.warning(f"QR não aceito: {exc}")
        if st.button("Ler outra etiqueta", key="ann_camera_reject_" + scope):
            st.session_state.pop(state_key, None)
            st.rerun()
        return
    st.success("QR lido. Confira os dados antes de adicionar ao rascunho.")
    st.text(f"Produto: {item.product} · {catalog[item.product]}\nLote: {item.lot}\nQuantidade: {item.quantity}")
    repeat = st.checkbox("Confirmo que é outra etiqueta física, se a leitura da câmera for igual",
                         key="ann_camera_repeat_" + scope)
    add, retry = st.columns(2)
    if add.button("Adicionar QR lido", type="primary", key="ann_camera_add_" + scope):
        def register():
            room.action(token, "add", stage, address, code, item=item, repeat=repeat)
            st.session_state.pop(state_key, None)
        _apply(st, register)
    if retry.button("Descartar leitura da câmera", key="ann_camera_discard_" + scope):
        st.session_state.pop(state_key, None)
        st.rerun()


def _capture(st, token, stage, address, code, lines, catalog):
    st.markdown(f"**Endereço {address}**" + (f" · Produto **{code}**" if code else ""))
    ident = f"{stage}_{address}_{code}"
    with st.container():
        _camera_capture(st, token, stage, address, code, ident, catalog)
    with st.form("ann_qr_" + ident, clear_on_submit=True):
        payload = st.text_input("Ler ou colar o QR da etiqueta", max_chars=180,
                                placeholder="00000001,000101,3")
        repeat = st.checkbox("Confirmo que é outra etiqueta física, se a leitura for igual")
        if st.form_submit_button("Adicionar leitura", type="primary"):
            def register():
                item = room.parse_demo_label(payload, address, catalog=catalog)
                room.action(token, "add", stage, address, code, item=item, repeat=repeat)
            _apply(st, register)
    with st.expander("Etiqueta antiga ou lançamento manual"):
        with st.form("ann_manual_" + ident, clear_on_submit=True, enter_to_submit=False):
            raw_product = st.text_input("Código do produto", max_chars=32)
            lot = st.text_input("Lote", max_chars=32)
            amount = st.text_input("Quantidade contada", max_chars=18)
            manual_repeat = st.checkbox("Confirmo que é outro volume, se o lançamento for igual")
            if st.form_submit_button("Adicionar lançamento manual"):
                def manual():
                    item = room.reading(raw_product, address, lot, amount, catalog=catalog)
                    room.action(token, "add", stage, address, code, item=item, repeat=manual_repeat)
                _apply(st, manual)
    if lines:
        st.caption(f"Rascunho salvo · {len(lines)} lançamento(s)")
        st.dataframe([dict(row, Descrição=catalog.get(row["Produto"], ""), Quantidade=float(row["Quantidade"])) for row in room.grouped(lines)],
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
                        item = room.reading(updated_product, address, updated_lot, updated_qty, selected["label_id"], catalog=catalog)
                        room.action(token, "edit", stage, address, code, item=item, line_id=line_id, expected=selected)
                    _apply(st, edit)
            if st.button("Remover leitura selecionada", key="ann_del_" + ident):
                _apply(st, room.action, token, "remove", stage, address, code, line_id=line_id, expected=selected)
    with st.form("ann_deliver_" + ident, enter_to_submit=False):
        empty = st.checkbox("Endereço conferido e vazio" if stage in (FIRST, room.EXTRA) else "Produto não encontrado")
        complete = st.checkbox("Conferi os lançamentos. Após enviar, não poderei editar." if stage == FIRST else "Conferi toda a tarefa")
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
                st.session_state.pop("_annual_camera_preview", None)
                st.session_state.pop("_annual_free_active", None)
                st.rerun()
            if stage == room.EXTRA:
                st.info("Conferência extra · Fora do total oficial.")
            _capture(st, token, stage, address, "", current["drafts"][key], current["catalog"])
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
        address = st.selectbox("Buscar endereço de estoque", options, index=None, filter_mode="contains",
                               placeholder="Digite parte do endereço", accept_new_options=False,
                               key="ann_search_" + current["room_id"])
        if st.button("Abrir endereço", type="primary", disabled=address is None):
            open_at(address)
    else:
        with st.form("ann_enter_address", clear_on_submit=True):
            address = st.text_input("Informe o endereço de estoque", max_chars=60)
            if st.form_submit_button("Abrir endereço", type="primary"):
                open_at(address)
    conflict = st.session_state.get("_annual_address_conflict")
    if conflict and conflict[0] == token:
        _, address, owner, message = conflict
        st.warning(f"{address}: {message} A conferência extra fica fora do total oficial.")
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
    else:
        address, code = st.selectbox("Posição para auditoria", tasks,
            format_func=lambda pair: " · ".join(pair), key="ann_audit_task")
    _capture(st, token, stage, address, code, current["drafts"][room.task_key(stage, address, code, current["role"])], current["catalog"])


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


def _select(st, access):
    for key in ("_ann_active_first", "_annual_free_active", "_annual_address_conflict",
                "_annual_last_sent_v3", "_annual_extra_sent", "_annual_camera_preview"):
        st.session_state.pop(key, None)
    if access is None:
        st.session_state.pop(STATE, None)
    else:
        st.session_state[STATE] = access
    st.rerun()


def _inventory_list(st, manager):
    st.subheader("Inventários disponíveis")
    listings = room.list_rooms(manager=manager)
    if not listings:
        st.info("Nenhum inventário disponível." if manager else "Nenhum inventário liberado pela gestão no momento.")
    for item in listings:
        with st.container(border=True):
            st.text(item["title"])
            if manager:
                status = "Encerrado" if item["closed"] else ("Liberado para contagem" if item["visible"] else "Somente gestão")
                st.caption(status)
                if st.button("Acompanhar inventário", key="ann_manage_" + item["id"]):
                    _select(st, room.RoomAccess(item["id"], room.COORD, True))
            elif item["teams"]:
                with st.container(key=f'ann_team_grid_{item["id"]}'):
                    for role, name in item["teams"]:
                        if st.button(name, key=f'ann_team_{item["id"]}_{role}', width="stretch"):
                            _select(st, room.RoomAccess(item["id"], role))


def render(st, *, manager=False, sign_in=None, sign_out=None):
    st.caption("Piloto · Dados fictícios")
    token = st.session_state.get(STATE)
    if isinstance(token, room.RoomAccess) and token.manager == manager:
        try:
            current = room.view(token)
        except ValueError as exc:
            st.session_state.pop(STATE, None)
            st.warning(str(exc))
        else:
            if current["role"] == room.AUDITOR:
                if st.button("Voltar ao andamento"):
                    _select(st, room.RoomAccess(current["room_id"], room.COORD, True))
            elif st.button("Voltar aos inventários"):
                _select(st, None)
            if current["role"] == room.COORD:
                _coordinator(st, token, current)
            else:
                st.text("Acesso: " + current["display"])
                st.caption(current["title"])
                st.button("Atualizar fila", key="ann_update", help="Busca alterações salvas pelas outras equipes.")
                _worker(st, token, current)
            return
    else:
        st.session_state.pop(STATE, None)
    if manager:
        joined, create = st.tabs(["Acompanhar", "Criar piloto"])
        with joined:
            _inventory_list(st, True)
            with st.expander("Restaurar cópia de segurança"):
                uploaded = st.file_uploader("Arquivo da cópia", type=["json"], max_upload_size=8,
                                            key="annual_backup_file")
                if uploaded and st.button("Restaurar piloto"):
                    try:
                        restored = room.restore_room(uploaded.getvalue(), manager=True)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        _select(st, restored)
        with create:
            _setup(st)
    else:
        _inventory_list(st, False)
    if sign_out is not None:
        label = "Sair do modo gestor" if manager else "Sair da conta"
        if st.button(label, key="ann_manager_logout", icon=":material/logout:"):
            sign_out()
    elif not manager and sign_in is not None:
        with st.expander("Entrar como gestor"):
            sign_in()
