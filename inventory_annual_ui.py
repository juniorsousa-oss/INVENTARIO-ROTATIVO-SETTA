"""Interface do Inventário Anual em modo piloto, sem integração operacional."""
from inventory_annual_pilot import AnnualPilot, CATALOG, ELIGIBLE, EXCLUDED, TEAMS, VALIDATED

STATE = "_annual_inventory_pilot_v1"
SUPERVISOR = "Coordenação"
AUDITOR = "Auditoria"
VIEWS = (SUPERVISOR, *TEAMS, AUDITOR)


def _number(st, label, key):
    return st.number_input(label, min_value=0.0, max_value=1_000_000_000.0,
                           value=None, step=1.0, format="%.6f", key=key)


def _apply(st, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.rerun()


def _setup(st, pilot):
    st.subheader("Preparar a contagem")
    st.caption("Distribua os endereços aptos do S2. A base fictícia será congelada ao iniciar.")
    with st.form("ann_setup"):
        assignment = {a: st.selectbox(f"Dupla para {a}", TEAMS, index=i // 2, key=f"ann_assign_{a}")
                      for i, a in enumerate(ELIGIBLE)}
        locked = st.checkbox("Confirmo o bloqueio simulado do S2")
        if st.form_submit_button("Iniciar piloto", type="primary"):
            _apply(st, pilot.start, assignment, locked)
    for address, reason in EXCLUDED.items():
        st.caption(f"{address} · Não apto: {reason}. Seu saldo de corte entra apenas na apuração final.")


def _coordinator(st, pilot):
    st.subheader("Acompanhar endereços")
    st.caption("Saldo de corte: " + pilot.started_at.strftime("%d/%m/%Y às %H:%M"))
    st.progress(sum(pilot.address_status(a) == VALIDATED for a in ELIGIBLE) / len(ELIGIBLE))
    st.dataframe([{"Endereço": a, "Dupla": pilot.assignment[a], "Situação": pilot.address_status(a)}
                  for a in ELIGIBLE], hide_index=True)
    if not pilot.closed_at:
        st.caption("O fechamento exige a entrega de todos os endereços e a conclusão das divergências.")
        if st.button("Fechar piloto e apurar", type="primary", disabled=not pilot.ready()):
            _apply(st, pilot.close)
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
    if st.checkbox("Confirmo que quero descartar esta simulação"):
        if st.button("Reiniciar piloto"):
            for key in tuple(st.session_state.keys()):
                if key == STATE or key.startswith("ann_"):
                    del st.session_state[key]
            st.rerun()


def _team(st, pilot, team):
    st.subheader("1ª contagem cega")
    allowed = [a for a in ELIGIBLE if pilot.assignment[a] == team and a not in pilot.positions]
    if not allowed:
        st.info("Sua dupla não tem endereços pendentes na 1ª contagem.")
    else:
        address = st.selectbox("Endereço da sua dupla", allowed, key=f"ann_addr_{team}")
        st.caption("Preencha só os produtos encontrados. Saldos e números de outras contagens não são exibidos.")
        with st.form(f"ann_first_{team}_{address}"):
            counts = {}
            for code, (description, _) in CATALOG.items():
                quantity = _number(st, f"{code} · {description}", f"ann_qty_{team}_{address}_{code}")
                if quantity is not None:
                    counts[code] = quantity
            empty = st.checkbox("Endereço conferido e vazio")
            complete = st.checkbox("Conferi todo o endereço e registrei o que encontrei")
            if st.form_submit_button("Entregar endereço", type="primary"):
                _apply(st, pilot.first, team, address, counts, empty=empty, complete=complete)
    st.divider()
    st.subheader("2ª contagem cega")
    queue = pilot.queue(team)
    if not queue:
        st.info("Nenhum item atribuído para recontagem.")
        return
    address, code = st.selectbox("Posição para recontar", queue, format_func=lambda pair: " · ".join(pair),
                                 key=f"ann_recount_pair_{team}")
    with st.form(f"ann_second_{team}_{address}_{code}"):
        number = _number(st, f"Quantidade da 2ª contagem de {code}", f"ann_second_qty_{team}_{address}_{code}")
        st.caption("Informe zero se não encontrar o produto.")
        if st.form_submit_button("Confirmar 2ª contagem", type="primary"):
            _apply(st, pilot.recount, team, address, code, number)


def _auditor(st, pilot):
    st.subheader("3ª contagem / Auditoria")
    queue = pilot.audit_queue()
    if not queue:
        st.info("Nenhuma posição aguardando auditoria.")
        return
    address, code = st.selectbox("Posição para auditoria", queue, format_func=lambda pair: " · ".join(pair),
                                 key="ann_audit_pair")
    with st.form(f"ann_audit_{address}_{code}"):
        number = _number(st, f"Quantidade apurada de {code}", f"ann_audit_qty_{address}_{code}")
        note = st.text_area("Justificativa da auditoria", max_chars=400, key=f"ann_audit_note_{address}_{code}")
        if st.form_submit_button("Validar auditoria", type="primary"):
            _apply(st, pilot.audit, address, code, number, note, AUDITOR)


def render(st):
    st.warning("PILOTO · Dados fictícios do S2. Sem integração com o estoque real ou o Protheus.")
    st.caption("As funções abaixo são simuladas no mesmo navegador. Os registros não são compartilhados e se perdem ao recarregar a página.")
    pilot = st.session_state.setdefault(STATE, AnnualPilot())
    if not pilot.started_at:
        _setup(st, pilot)
        return
    view = st.selectbox("Papel simulado", VIEWS, key="ann_role")
    if view == SUPERVISOR:
        _coordinator(st, pilot)
    elif pilot.closed_at:
        st.info("Piloto encerrado. Consulte o fechamento na visão Coordenação.")
    elif view == AUDITOR:
        _auditor(st, pilot)
    else:
        _team(st, pilot, view)
