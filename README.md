# Inventário Rotativo | SETTA

Aplicativo operacional em Streamlit para execução e acompanhamento de inventários rotativos, contagens, recontagens, auditorias, inconsistências e histórico de estoque.

## Execução

```bash
pip install -r requirements.txt
streamlit run app.py
```

Ambiente validado: Python 3.11 com as versões fixadas em `requirements.txt`.

## Padrão SETTA

O aplicativo utiliza o shell oficial SETTA:

- moldura externa e rolagem interna;
- botão superior e drawer lateral;
- header/logo central;
- responsividade desktop/mobile;
- sidebar com sessão e status das fontes.

O shell fica isolado em `setta_shell.py`. A interface operacional do Inventário permanece independente.

## Módulos

- Dashboard
- Inventário Rotativo
- Banco de Dados
- Registro
- Reportar Inconsistências
- Configurações

## Fontes e desempenho

A Central SETTA fornece `analitico`, `endereco` e a base derivada `estoque_tratado`.

A base operacional da sessão é reconstruída por ANALÍTICO + ENDEREÇO e mantida em cache por `version_token`. O app não lê mais milhares de registros do Firestore no caminho crítico de cada sessão.

Fluxo atual:

`Central SETTA -> snapshot em cache -> sessão Streamlit`

Firestore e SQLite permanecem somente como contingência de leitura. O SQLite utiliza diretório temporário e não deve ser considerado persistência definitiva.

A identidade visual usa `visual_shell_get`, que transfere apenas logo e `ui_config`, sem carregar o favicon em base64 no startup.

## Persistência operacional

O Supabase é a fonte persistente de configurações, inventários, ciclos e inconsistências.

As gravações principais não substituem mais o JSON operacional completo:

- `inventory_document_upsert` grava somente o documento alterado;
- `inventory_report_upsert` grava somente a inconsistência alterada;
- `inventory_cycles_merge` é usado na migração de ciclos antigos;
- `inventory_close_atomic` encerra documento, ciclos e inconsistências na mesma transação;
- `inventory_next_document` gera a numeração diária atomicamente no banco.

As funções PostgreSQL correspondentes são `SECURITY DEFINER` e só concedem execução a `service_role`.

## Autenticação e perfis

O cadastro de usuários continua centralizado no OperaHub.

Enquanto a política global `login_required` estiver desligada, leitura e operação básica podem abrir como **Operador não identificado**. A sidebar permite identificação voluntária com o mesmo usuário e senha do OperaHub.

O perfil não pode mais ser selecionado manualmente:

- usuário anônimo ou usuário comum -> **Operador**;
- role `admin` ou `gestor` autenticada -> **Gestor**.

Ao autenticar, a `setta-data-api` cria uma sessão temporária específica do Inventário, válida por 8 horas. O token é necessário no backend para:

- encerrar um inventário;
- salvar configurações administrativas.

Logout invalida a sessão no servidor.

Contagens, inventários e inconsistências novos registram usuário/perfil quando disponíveis.

## Horário

Eventos criados pelo app utilizam explicitamente `America/Sao_Paulo`. Datas ISO são armazenadas para ordenação/auditoria e formatadas em PT-BR na interface.

## Regras principais

- ESTOQUE ANALÍTICO: código, descrição, saldo e valor;
- ENDEREÇO: posição e quantidade por material;
- endereços não disponíveis são excluídos da base apta;
- inventário suporta primeira contagem, recontagens, auditoria e encerramento pelo gestor;
- contagem cega pode ser usada por padrão;
- inconsistências abertas entram automaticamente no próximo inventário elegível;
- histórico mantém as contagens por posição;
- Banco de Dados consulta `estoque_tratado` da Central em modo somente leitura.

## Estrutura

- `app.py`: regras operacionais e páginas;
- `setta_shell.py`: shell SETTA;
- `setta_auth.py`: login e sessão administrativa;
- `central_inventory_data.py`: Central SETTA e contratos de dados;
- `scripts/validate_base.py`: validação automática da baseline;
- `supabase/migrations/`: histórico das alterações de banco;
- `.streamlit/config.toml`: configuração Streamlit;
- `.github/workflows/central-inventory-ci.yml`: CI;
- `.gitignore`: proteção de secrets, SQLite e arquivos locais.

## Validação

O CI compila os módulos e executa `scripts/validate_base.py`. Entre outras regressões, o teste bloqueia:

- retorno do CSS antigo da sidebar;
- bypass fixo de autenticação;
- perfil Gestor selecionável manualmente;
- retorno de persistências legadas;
- SQLite no diretório do projeto;
- perda das operações atômicas;
- perda da autenticação administrativa;
- alteração não controlada de páginas/dependências;
- retorno do Firestore ao caminho crítico de inicialização.

## Pendência estrutural futura

A persistência atual já evita sobrescrita global entre documentos diferentes, mas cada documento de inventário ainda é salvo como um JSON único. Para colaboração simultânea de vários operadores no **mesmo documento**, a evolução recomendada é normalizar `documentos`, `itens` e `contagens` em tabelas separadas.

Essa evolução não é necessária para validar o build atual, mas é o próximo passo caso o mesmo inventário passe a ser contado simultaneamente por várias pessoas.
