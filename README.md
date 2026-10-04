# Inventário Rotativo | SETTA

Aplicativo operacional em Streamlit para execução e acompanhamento de inventários rotativos, contagens, recontagens, auditorias, inconsistências e histórico de estoque.

## Execução

```bash
pip install -r requirements.txt
streamlit run app.py
```

Ambiente validado: Python 3.11 com as versões fixadas em `requirements.txt`.

## Padrão SETTA

O aplicativo utiliza o shell oficial extraído do Conversor MRP:

- moldura externa e rolagem interna;
- menu superior com botão de abertura;
- sidebar operacional;
- header/logo via configuração global `setta_global`;
- comportamento responsivo desktop/mobile.

O shell fica isolado em `setta_shell.py`. O conteúdo interno do Inventário continua independente.

## Módulos

- Dashboard
- Inventário Rotativo
- Banco de Dados
- Registro
- Reportar Inconsistências
- Configurações

## Fontes de dados

A Central SETTA fornece:

- `analitico`;
- `endereco`;
- base derivada `estoque_tratado`.

O aplicativo compara tokens de versão antes de reprocessar as fontes e registra o status por consumidor em `setta_consumer_sync_state`.

## Persistência operacional

O estado operacional principal de configurações, inventários, ciclos e inconsistências utiliza o Supabase por meio da ação `inventory_state_get/set`.

A base consolidada de estoque, posições e endereços habilitados ainda possui contingência em Firestore/SQLite. Essa camada é mantida nesta baseline para evitar alteração funcional durante a padronização e será avaliada separadamente antes de qualquer remoção.

## Autenticação

O aplicativo está integrado à autenticação central do OperaHub por `setta_auth.py`.

- a política global `login_required` decide se o login é obrigatório;
- quando desligada, o uso permanece como hoje;
- quando ligada, o app solicita o mesmo usuário/senha do OperaHub;
- se a política central não puder ser confirmada, o acesso adota comportamento fail-closed.

## Regras principais

- ESTOQUE ANALÍTICO: código, descrição, saldo e valor;
- ENDEREÇO: posição e quantidade por material;
- endereços não disponíveis são excluídos da base apta;
- inventário suporta primeira contagem, recontagens sem limite, auditoria e encerramento pelo gestor;
- contagem cega pode ser usada por padrão;
- inconsistências abertas entram automaticamente no próximo inventário elegível;
- histórico mantém todas as contagens por posição;
- Banco de Dados consulta o `estoque_tratado` publicado pela Central em modo somente leitura.

## Estrutura

- `app.py`: regras operacionais e páginas;
- `setta_shell.py`: Padrão SETTA;
- `setta_auth.py`: autenticação central;
- `central_inventory_data.py`: Central SETTA e persistência operacional Supabase;
- `scripts/validate_base.py`: validação automática da baseline;
- `.streamlit/config.toml`: tema e configuração do Streamlit;
- `.github/workflows/central-inventory-ci.yml`: CI.

## Validação

O CI compila os módulos e executa `scripts/validate_base.py`, bloqueando regressões como retorno de CSS legado da sidebar, perda do shell SETTA, bypass fixo de autenticação, alteração não controlada das páginas ou dependências e perda dos contratos da Central.
