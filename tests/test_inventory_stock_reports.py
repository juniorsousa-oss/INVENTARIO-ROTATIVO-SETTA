"""Regressão: custo/armazém/endereços/contagens e 2 planilhas Protheus.

Dados totalmente sintéticos; nunca acessa o Supabase em testes.
"""
import io
import unittest
from datetime import datetime
from zipfile import ZipFile

import pandas as pd

from inventory_stock_reports import (
    GERAL_CONFERENCIA, GERAL_AUDITORIA, ENDERECOS_COLS,
    NAO_ENDERECADOS, build_stock_reports, exportar_excel,
)


def sample_sources():
    # A=Produto, D=Descrição, G=ARMZ, H=Saldo, K=Valor contábil
    analitico = pd.DataFrame([
        ["158", "", "", "MATERIAL A", "", "", "S2", 100, "", "", 2500],
        ["158", "", "", "MATERIAL A", "", "", "EP", 10, "", "", 500],
        ["295", "", "", "MATERIAL B", "", "", "S2", 20, "", "", 800],
        ["339", "", "", "MATERIAL C", "", "", "EP", 5, "", "", 50],
    ])
    # A=Produto, B=Armazém, D=Endereço, H=Quantidade
    endereco = pd.DataFrame([
        ["158", "S2", "", "A001", "", "", "", 30],
        ["158", "S2", "", "A001", "", "", "", 20],  # lote adicional
        ["158", "S2", "", "A002", "", "", "", 25],
        ["158", "S2", "", "QUALIDADE", "", "", "", 5],  # não disponível
        ["158", "EP", "", "E001", "", "", "", 7],
        ["295", "S2", "", "B001", "", "", "", 28],  # excesso de endereçamento
        # 339 sem endereço -> toda disponibilidade na posição virtual
    ])
    treated = pd.DataFrame([
        {"COD_MATERIAL": "00000158", "DESCRICAO": "MATERIAL A",
         "SALDO_EM_ESTOQUE": 110, "SALDO_NAO_DISPONIVEL": 5,
         "SALDO_DISPONIVEL": 105},
        {"COD_MATERIAL": "00000295", "DESCRICAO": "MATERIAL B",
         "SALDO_EM_ESTOQUE": 20, "SALDO_NAO_DISPONIVEL": 0,
         "SALDO_DISPONIVEL": 20},
        {"COD_MATERIAL": "00000339", "DESCRICAO": "MATERIAL C",
         "SALDO_EM_ESTOQUE": 5, "SALDO_NAO_DISPONIVEL": 0,
         "SALDO_DISPONIVEL": 5},
    ])
    count = {
        "INV0001": {
            "status": "FECHADO",
            "rows": [
                {"codigo": "00000158", "armazem": "S2", "endereco": "A001",
                 "contagens": [
                     {"etapa": "1ª CONTAGEM", "timestamp": "2026-11-19T12:00:00-03:00"},
                     {"etapa": "RECONTAGEM", "timestamp": "2026-11-20T12:00:00-03:00"},
                 ]},
            ],
        },
        "INV0002": {
            "status": "EM APURAÇÃO",
            "rows": [
                {"codigo": "00000158", "armazem": "S2", "endereco": "A002",
                 "contagens": [
                     {"etapa": "AUDITORIA", "timestamp": "2026-11-22T13:20:00-03:00"},
                 ]},
                {"codigo": "00000295", "armazem": "S2", "endereco": "B001",
                 "contagens": []},
            ],
        },
    }
    return treated, analitico, endereco, count


class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.treated, self.analytic, self.addresses, self.history = sample_sources()
        self.args = (
            self.treated, self.analytic, self.addresses,
            self.history, {"QUALIDADE"},
        )

    def test_armazens_sem_misturar_precos_e_posicoes(self):
        result = build_stock_reports(*self.args)
        self.assertEqual(result["armazens"], ["EP", "S2"])
        geral = result["conferencia"]
        self.assertEqual(geral.columns.tolist(), GERAL_CONFERENCIA)
        self.assertEqual(len(geral), 4)
        a_s2 = geral[(geral["Código"] == "00000158") & (geral["Armazém"] == "S2")].iloc[0]
        a_ep = geral[(geral["Código"] == "00000158") & (geral["Armazém"] == "EP")].iloc[0]
        self.assertEqual(a_s2["Saldo em Estoque"], 100)
        self.assertEqual(a_s2["Saldo Não Disponível"], 5)
        self.assertEqual(a_s2["Saldo Disponível"], 95)
        self.assertEqual(a_s2["Valor Unitário"], 25)
        self.assertEqual(a_s2["Valor em Estoque"], 2375)
        self.assertEqual(a_ep["Saldo Disponível"], 10)
        self.assertEqual(a_ep["Valor Unitário"], 50)
        self.assertEqual(a_ep["Valor em Estoque"], 500)

    def test_ultima_contagem_conta_cada_etapa_e_inventarios_abertos(self):
        result = build_stock_reports(*self.args)
        line = result["conferencia"].query("Código == '00000158' and Armazém == 'S2'").iloc[0]
        self.assertEqual(line["Quantidade de Contagens"], 3)
        self.assertEqual(line["Data da Última Contagem"], "22/11/2026")
        ep = result["conferencia"].query("Código == '00000158' and Armazém == 'EP'").iloc[0]
        self.assertTrue(pd.isna(ep["Quantidade de Contagens"]))
        self.assertEqual(ep["Data da Última Contagem"], "")

    def test_nao_enderecados_apenas_diferenca_positiva_por_codigo_armazem(self):
        result = build_stock_reports(*self.args)
        positions = result["enderecos"]
        non = positions[positions["Endereço"] == NAO_ENDERECADOS]
        self.assertEqual(result["nao_enderecados"], 3)
        p_s2 = non.query("Código == '00000158' and Armazém == 'S2'").iloc[0]
        self.assertEqual(p_s2["Quantidade no Endereço"], 20)
        self.assertEqual(p_s2["Valor no Endereço"], 500)
        p_ep = non.query("Código == '00000158' and Armazém == 'EP'").iloc[0]
        self.assertEqual(p_ep["Quantidade no Endereço"], 3)
        p_339 = non.query("Código == '00000339' and Armazém == 'EP'").iloc[0]
        self.assertEqual(p_339["Quantidade no Endereço"], 5)
        self.assertEqual(p_339["Valor no Endereço"], 50)
        self.assertFalse(non["Quantidade no Endereço"].le(0).any())
        self.assertNotIn("QUALIDADE", positions["Endereço"].tolist())
        real_a = positions.query("Código == '00000158' and Armazém == 'S2' and Endereço == 'A001'")
        self.assertEqual(real_a["Quantidade no Endereço"].tolist(), [50])

    def test_endereco_maior_que_disponivel_gera_alerta_sem_saldo_negativo(self):
        result = build_stock_reports(*self.args)
        self.assertEqual(result["divergencias_enderecos"], 1)
        self.assertTrue(any("MAIOR" in s for s in result["avisos"]))
        no = result["enderecos"].query("Código == '00000295' and Endereço == @NAO_ENDERECADOS")
        self.assertTrue(no.empty)
        self.assertEqual(
            result["enderecos"].query("Código == '00000295'")["Quantidade no Endereço"].sum(), 28
        )

    def test_filtro_recalcula_rankings_e_mantem_codigo_com_zeros(self):
        result = build_stock_reports(*self.args, armazem="EP")
        geral = result["conferencia"]
        positions = result["enderecos"]
        self.assertEqual(set(geral["Armazém"]), {"EP"})
        self.assertEqual(geral["Código"].tolist(), ["00000158", "00000339"])
        self.assertEqual(geral["Classificação por Valor Unitário"].tolist(), ["1º", "2º"])
        self.assertEqual(geral["Classificação por Valor Agregado"].tolist(), ["1º", "2º"])
        self.assertEqual(set(positions["Armazém"]), {"EP"})
        self.assertEqual(result["saldo_disponivel_total"], 15)
        with self.assertRaisesRegex(ValueError, "Armazém não encontrado"):
            build_stock_reports(*self.args, armazem="XX")

    def test_divergencia_central_sinalizada_sem_distribuir_diferenca(self):
        treated = self.treated.copy()
        treated.loc[0, "SALDO_DISPONIVEL"] = 106
        result = build_stock_reports(
            treated, self.analytic, self.addresses, self.history, {"QUALIDADE"}
        )
        self.assertEqual(result["divergencias_central"], 1)
        self.assertTrue(any("Estoque Tratado" in s for s in result["avisos"]))
        # Não é correto ratear +1 em um armazém não identificado.
        self.assertEqual(result["conferencia"]["Saldo Disponível"].sum(), 130)

    def test_excel_duas_abas_colunas_e_total_numerico_zeros_esquerda(self):
        result = build_stock_reports(*self.args)
        for modelo, expected in (
            ("Conferência", GERAL_CONFERENCIA),
            ("Auditoria", GERAL_AUDITORIA),
        ):
            general = result["conferencia" if modelo == "Conferência" else "auditoria"]
            self.assertEqual(general.columns.tolist(), expected)
            excel = exportar_excel(general, result["enderecos"], modelo, "TODOS")
            self.assertTrue(excel.startswith(b"PK"))
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(excel), read_only=False, data_only=False)
            self.assertEqual(wb.sheetnames, ["Estoque Geral", "Estoque por Endereço"])
            ws = wb["Estoque Geral"]
            self.assertEqual(ws["A1"].value, "Código")
            self.assertEqual(ws["A2"].data_type, "s")
            self.assertEqual(ws["A2"].value, "00000158")
            self.assertEqual(
                [ws.cell(1, c).value for c in range(1, len(expected) + 1)],
                expected,
            )
            self.assertEqual(
                [wb["Estoque por Endereço"].cell(1, c).value for c in range(1, 9)],
                ENDERECOS_COLS,
            )
            self.assertTrue(ws.auto_filter.ref)
            self.assertTrue(ws.freeze_panes)
            self.assertEqual(ws.cell(ws.max_row, 1).value, "TOTAL")
            wb.close()


if __name__ == "__main__":
    unittest.main()
