"""Interface de pilotos simulados e de validação privada com amostras reais."""
from functools import partial
from hashlib import sha256

from inventory_annual_camera import scan_label
from inventory_annual_real import read_export, sample
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


def _setup(st, excluded=()):
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
    source = st.radio("Base do piloto", ["Fictícia", "Amostra real privada"], horizontal=True)
    real = source == "Amostra real privada"
    if real:
        left, right = st.columns(2)
        end = left.file_uploader("Relatório ENDEREÇO", type=["xlsx", "xltx"], max_upload_size=20)
        analytic = right.file_uploader("Relatório ANALÍTICO", type=["xlsx", "xltx"], max_upload_size=20)
        locations = st.text_area("Endereços para validar (um por linha)", max_chars=2000)
    if st.button("Iniciar piloto", type="primary", disabled=real and not (end and analytic and locations.strip())):
        def start():
            selected = (sample(read_export(end.getvalue(), "ENDEREÇO"),
                               read_export(analytic.getvalue(), "ANALÍTICO"),
                               locations, excluded=excluded) if real else None)
            token = room.create_room({}, True, people=plan["people"], title=plan["title"],
                mode=plan["mode"], participants=plan["participants"], assignments=plan.get("assignments"), sample=selected)
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
    st.caption("Amostra real privada" if current["real_sample"] and not closed else status)

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
    if pilot.free and not current["visible"] and not current["real_sample"]:
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
    if current["real_sample"] and not pilot.closed_at:
        with st.expander("Testar como equipe"):
            for role, name in [(idx, data["name"]) for idx, data in current["teams"].items()] + (
                    [(room.INDEPENDENT, room.INDEPENDENT)] if len(current["teams"]) == 1 else []):
                if st.button(name, key="ann_preview_real_" + role):
                    _select(st, room.RoomAccess(current["room_id"], role, True))
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
        st.download_button(
            "Baixar cópia do piloto", data=partial(room.backup_room, token),
            file_name=f'inventario-anual-{current["room_id"]}.json',
            mime="application/json", on_click="ignore", key="annual_download_backup",
            icon=":material/download:",
        )


def _coordinator_result(st, current):
    pilot = current["pilot"]
    st.success("Piloto encerrado.")
    st.subheader("Resultado da amostra por produto" if current["real_sample"] else "Fechamento por produto")
    frame = [{"Código": code, "Produto": desc, "Contado (aptos)": float(counted),
              "Saldo não apto": float(excl), "Total apurado": float(final),
              ("Saldo da amostra no corte" if current["real_sample"] else "Saldo de estoque no corte"): float(system), "Dif. quantidade": float(delta),
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


def _capture(st, token, stage, address, code, lines, catalog):
    st.markdown(f"**Endereço {address}**" + (f" · Produto **{code}**" if code else ""))
    ident = f"{stage}_{address}_{code}"
    scope = sha256(f"{token}:{ident}".encode()).hexdigest()[:24]
    pending_key = "_annual_edition_pending"
    pending = st.session_state.get(pending_key)
    if pending and pending[0] != scope:
        pending = None
        st.session_state.pop(pending_key, None)

    def stage_item(payload, *, review=False):
        payload = (payload or "").strip()
        if room.FIELD.fullmatch(payload.upper()):
            product = room.resolve_product(payload, catalog)
            if code and product != code:
                raise ValueError("O código não pertence ao produto desta tarefa.")
            st.session_state[pending_key] = (scope, "simple", product)
            st.rerun()
        item = room.parse_demo_label(payload, address, catalog=catalog)
        if code and item.product != code:
            raise ValueError("A etiqueta não pertence ao produto desta tarefa.")
        if review:
            st.session_state[pending_key] = (scope, "review", item)
            st.rerun()
        write(item)

    def write(item, repeat=False):
        try:
            room.action(token, "add", stage, address, code, item=item, repeat=repeat)
        except room.IdenticalReading:
            st.session_state[pending_key] = (scope, "repeat", item)
            st.rerun()
        else:
            st.session_state.pop(pending_key, None)
            st.rerun()

    with st.form("ann_bip_" + scope, clear_on_submit=True):
        payload = st.text_input("Bipar etiqueta", max_chars=180, placeholder="Bipe, cole ou digite o código")
        if st.form_submit_button("Adicionar leitura", type="primary", disabled=bool(pending)):
            try:
                stage_item(payload)
            except ValueError as exc:
                st.error(str(exc))

    def manual(product="", *, prefix="manual"):
        with st.form(f"ann_{prefix}_{scope}", clear_on_submit=True, enter_to_submit=False):
            raw = st.text_input("Código do produto", value=product or code, max_chars=32,
                                disabled=bool(product or code))
            lot = st.text_input("Lote", max_chars=32)
            amount = st.text_input("Quantidade contada", max_chars=18)
            if st.form_submit_button("Adicionar lançamento"):
                try:
                    write(room.reading(raw, address, lot, amount, catalog=catalog))
                except ValueError as exc:
                    st.error(str(exc))

    if pending:
        _, kind, value = pending
        if kind == "simple":
            st.info(f"{value} · {catalog[value]}. Informe o lote e a quantidade.")
            manual(value, prefix="complete")
        else:
            st.text(f"{value.product} · {catalog[value.product]} · Lote {value.lot} · Qtd. {value.quantity}")
            if kind == "repeat":
                st.warning("Leitura idêntica. Some apenas se for outro volume físico.")
            if st.button("Somar outro volume" if kind == "repeat" else "Adicionar etiqueta lida",
                         type="primary", key="ann_confirm_" + scope):
                _apply(st, write, value, kind == "repeat")
        if st.button("Descartar leitura", key="ann_discard_" + scope):
            st.session_state.pop(pending_key, None)
            st.rerun()
    else:
        with st.expander("Outra forma de lançar"):
            mode = st.radio("Forma de lançamento", ["Câmera", "Manual"], horizontal=True,
                            key="ann_entry_mode_" + scope, label_visibility="collapsed")
            if mode == "Câmera":
                result = scan_label("ann_cam_" + scope)
                if result is not None:
                    try:
                        stage_item(result, review=True)
                    except ValueError as exc:
                        st.error(f"Etiqueta não aceita: {exc}")
            else:
                manual()
    if lines:
        label = "1 lançamento salvo" if len(lines) == 1 else f"{len(lines)} lançamentos salvos"
        with st.expander(f"Revisar rascunho · {label}"):
            st.dataframe([dict(row, Descrição=catalog.get(row["Produto"], ""), Quantidade=float(row["Quantidade"]))
                          for row in room.grouped(lines)], hide_index=True, width="stretch")
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
    with st.expander("Revisar e enviar"):
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
                st.session_state.pop("_annual_edition_pending", None)
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

    conflict = st.session_state.get("_annual_address_conflict")
    if conflict and conflict[0] == token:
        _, address, owner, message = conflict
        st.warning(f"{address}: {message} A conferência extra fica fora do total oficial.")
        if st.button("Confirmar conferência extra"):
            open_at(address, owner)
        if st.button("Cancelar e escolher outro endereço"):
            st.session_state.pop("_annual_address_conflict", None)
            st.rerun()
        return
    options = current["address_options"]
    if options:
        address = st.selectbox("Bipe ou digite o endereço", options, index=None,
                               placeholder="Busque um endereço cadastrado",
                               accept_new_options=False, filter_mode="contains",
                               key="ann_address_filter_" + current["room_id"])
        if st.button("Abrir endereço", type="primary", disabled=address not in options):
            open_at(address)
    else:
        st.info("Nenhum endereço cadastrado está apto para contagem.")
    saved = [(stage, a) for stage in (FIRST, room.EXTRA) for a, _ in current["tasks"].get(stage, [])]
    if saved:
        with st.expander(f"Retomar rascunho ({len(saved)})"):
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
        address, code = st.selectbox("O que recontar", tasks,
            format_func=lambda pair: " · ".join(pair), key="ann_second_task")
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
        active = st.session_state.get("_annual_free_active")
        counting = bool(active and active[0] == token) or bool(st.session_state.get("_ann_active_first"))
        if not counting and tasksets.get(SECOND):
            step = st.segmented_control("Etapa", ["Contagem", "Recontagem"], default="Contagem",
                                        required=True, label_visibility="collapsed",
                                        key=f'ann_worker_stage_{current["room_id"]}_{current["role"]}')
            if step == "Recontagem":
                _worker_stage(st, token, current, SECOND)
                return
        _worker_stage(st, token, current, FIRST)
        if not counting:
            st.button("Atualizar fila", key="ann_update")
    elif SECOND in tasksets:
        st.subheader("Recontagem")
        _worker_stage(st, token, current, SECOND)
    else:
        st.subheader("Auditoria")
        _worker_stage(st, token, current, AUDIT)


def _select(st, access):
    for key in ("_ann_active_first", "_annual_free_active", "_annual_address_conflict",
                "_annual_last_sent_v3", "_annual_extra_sent", "_annual_edition_pending"):
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
            if item.get("real_sample"):
                st.caption("Amostra real privada")
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


def render(st, *, manager=False, sign_in=None, sign_out=None, excluded=()):
    if not manager:
        st.caption("Piloto · Dados fictícios")
    token = st.session_state.get(STATE)
    if isinstance(token, room.RoomAccess) and token.manager == manager:
        try:
            current = room.view(token)
        except ValueError as exc:
            st.session_state.pop(STATE, None)
            st.warning(str(exc))
        else:
            if current["role"] == room.AUDITOR or (token.manager and current["role"] != room.COORD):
                if st.button("Voltar ao andamento"):
                    _select(st, room.RoomAccess(current["room_id"], room.COORD, True))
            elif st.button("Voltar aos inventários"):
                _select(st, None)
            if current["role"] == room.COORD:
                _coordinator(st, token, current)
            else:
                st.text("Acesso: " + current["display"])
                st.caption("Amostra real privada" if current["real_sample"] else current["title"])
                if current["role"] == room.AUDITOR or FIRST not in current["tasks"]:
                    st.button("Atualizar fila", key="ann_update")
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
            _setup(st, excluded)
    else:
        _inventory_list(st, False)
    if sign_out is not None:
        label = "Sair do modo gestor" if manager else "Sair da conta"
        if st.button(label, key="ann_manager_logout", icon=":material/logout:"):
            sign_out()
    elif not manager and sign_in is not None:
        with st.expander("Entrar como gestor"):
            sign_in()
