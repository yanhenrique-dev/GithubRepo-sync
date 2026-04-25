

# 🚀 Update Repos - Atualizador de Repositórios GitHub

<div align="center">

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![License](https://img.shields.io/github/license/yanhenrique-dev/GithubRepo-sync)
![Status](https://img.shields.io/badge/status-active-success.svg)
![Maintenance](https://img.shields.io/badge/maintained-yes-green.svg)

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=24&duration=3000&pause=1000&color=00D9FF&center=true&vCenter=true&width=700&lines=Atualize+seus+reposit%C3%B3rios+GitHub+automaticamente!;Interface+Rich+interativa+e+colorida!;Downloads+paralelos+com+barra+de+progresso!;Cache+inteligente+e+rate+limit+tratado!" alt="Typing SVG" />

</div>

---

## 📋 Índice

- [🎯 Sobre o Projeto](#-sobre-o-projeto)
- [✨ Funcionalidades](#-funcionalidades)
- [🎬 Demonstração](#-demonstração)
- [📦 Instalação](#-instalação)
- [🚀 Como Usar](#-como-usar)
- [⚙️ Configuração](#️-configuração)
- [🗂️ Estrutura do Projeto](#️-estrutura-do-projeto)
- [🤝 Contribuindo](#-contribuindo)
- [📄 Licença](#-licença)

---

## 🎯 Sobre o Projeto

O **Update Repos** é uma ferramenta CLI (Command Line Interface) poderosa em Python desenvolvida para automatizar a manutenção de backups de repositórios GitHub. Ele monitora, baixa e gerencia arquivos ZIP de múltiplos repositórios, garantindo que você sempre tenha a versão mais recente localmente.

### 🎨 Por que usar?

*   **Interface Rica:** Experiência visual agradável usando a biblioteca **Rich**, com tabelas coloridas, barras de progresso em tempo real e feedback visual claro.
*   **Alta Performance:** Downloads paralelos (multithreading) e verificação assíncrona para economizar tempo.
*   **Resiliência:** Sistema de **Retry** automático em caso de falhas de rede e tratamento inteligente do *Rate Limit* da API do GitHub.
*   **Flexibilidade:** Funciona com ou sem Token, permitindo filtrar quais repositórios atualizar e gerar relatórios em JSON.

---

## ✨ Funcionalidades

| Funcionalidade | Descrição | Status |
|:---|:---|:---:|
| 🔍 **Verificação Inteligente** | Compara datas de modificação local vs remota (API) | ✅ |
| 📥 **Downloads Paralelos** | Até 4 threads simultâneas para download rápido | ✅ |
| 🎨 **Interface Rich** | Tabelas estilizadas, cores e progresso visual (ou fallback simples) | ✅ |
| 🔐 **Autenticação** | Suporte a Personal Access Tokens (Pat) | ✅ |
| 💾 **Cache de API** | Armazena metadados para evitar chamadas desnecessárias | ✅ |
| 🎯 **Seleção Interativa** | Menu toggle para escolher quais repos atualizar | ✅ |
| 📊 **Relatório JSON** | Gera log estruturado das operações realizadas | ✅ |
| 🚫 **Filtros Avançados** | Opções `--repos` (incluir) e `--skip` (excluir) | ✅ |
| 🔄 **Retry Automático** | 3 tentativas automáticas em falhas de download | ✅ |
| 📝 **Verificação MD5** | (Opcional) Garante integridade dos arquivos baixados | ✅ |

---

## 🎬 Demonstração

A ferramenta se adapta ao seu ambiente. Se tiver o `rich` instalado, você obtém a experiência completa. Caso contrário, usa um fallback limpo em texto puro.

### Interface Rich (Recomendado)
*Instale com: `pip install rich`*

<div align="center">

```text
╭─ GitHub Repo Updater ───────────────────────────────────────────╮
│ update_repos v2.1                                               │
│ Dir: /home/yan/Documentos/Code/Salvos do Github                 │
│ Token: ✗  Workers: 4  Rate Limit: 60/hr                         │
╰──────────────────────────────────────────────────────────────────╯

─── Verificando repositórios ─────────────────────────────────────
Consultando API...  [████████████████████] 17/17 100%

┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ # ┃ Arquivo                   ┃ Repositório               ┃ Status       ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 1 │ claw-code-main.zip        │ ultraworkers/claw-code   │ ⬆️  outdated │
│ 2 │ langflow-main.zip        │ langflow-ai/langflow     │ ⬆️  outdated │
│ 3 │ hermes-agent-main.zip    │ NousResearch/hermes      │ ⬆️  outdated │
│ 4 │ openclaude-main.zip      │ Gitlawb/openclaude       │ ✅ up_to_date│
└───┴──────────────────────────┴──────────────────────────┴──────────────┘

Selecione os repos para atualizar (nº para toggle, a= todos, n= nenhum, Enter= confirmar):
```
</div>

### Terminal Simples (Fallback)
*Ideal para scripts ou servidores sem UI*

```bash
python update_repos.py --check-only
```

```text
============================================================
update_repos v2.1 | dir: /home/yan/Code/Repos
============================================================
[CHECK] claw-code-main.zip ... (outdated)
[CHECK] langflow-main.zip .... (outdated)
[OK]    openclaude-main.zip ... (up_to_date)
------------------------------------------------------------
Summary: 2 outdated, 1 updated.
```

---

## 📦 Instalação

### Pré-requisitos
- Python 3.8 ou superior.
- (Opcional) `pip install rich` para interface melhorada.

### 1️⃣ Clone o repositório
```bash
git clone https://github.com/yanhenrique-dev/GithubRepo-sync.git
cd GithubRepo-sync
```

### 2️⃣ Dependências (Opcional)
Para a interface visual colorida:
```bash
pip install rich
```

### 3️⃣ Configuração do Token (Recomendado)
Para evitar o limite de 60 requisições/hora do GitHub e aumentar para 5000/hr:

**Linux/Mac (zsh/bash):**
```bash
export GITHUB_TOKEN="ghp_seu_token_aqui"
```

**Windows (PowerShell):**
```powershell
$env:GITHUB_TOKEN="ghp_seu_token_aqui"
```

> 💡 **Nota:** Você pode criar seu token em [GitHub Settings > Developer Settings > Personal Access Tokens](https://github.com/settings/tokens).

---

## 🚀 Como Usar

### Comandos Básicos

```bash
# Verifica quais repositórios estão desatualizados (sem baixar)
python update_repos.py --check-only

# Atualiza tudo automaticamente (sem interação)
python update_repos.py --auto

# Modo Interativo (Padrão) - Escolha o que baixar
python update_repos.py
```

### Filtros Avançados

```bash
# Atualizar apenas repositórios específicos
python update_repos.py --repos "claw-code-main.zip, langflow-main.zip"

# Pular repositórios específicos
python update_repos.py --skip "flai-master.zip, opensquad-master.zip"

# Usar um diretório específico
python update_repos.py --dir "/caminho/para/outros/zips"

# Log detalhado em arquivo
python update_repos.py --verbose --log update_log.txt
```

### Exemplo Completo (Power User)
```bash
python update_repos.py --auto --workers 8 --token "ghp_xxx" --verbose
```

---

## ⚙️ Configuração

Você pode criar um arquivo `update_repos.json` na raiz do projeto para evitar passar argumentos toda vez:

```json
{
  "token": "ghp_sua_chave_aqui",
  "workers": 4,
  "auto": false,
  "output_dir": "./downloads",
  "check_only": false
}
```

### Variáveis de Ambiente Suportadas
| Variável | Descrição |
|:---|:---|
| `GITHUB_TOKEN` | Seu token de acesso pessoal do GitHub. |
| `NO_COLOR` | Define como `1` para forçar modo sem cores. |

---

## 🗂️ Estrutura do Projeto

```text
update-repos/
├── 📄 update_repos.py       # Script principal (Core)
├── 📄 update_repos.json     # Configurações locais (Opcional)
├── 📄 .repo_cache.json      # Cache da API para performance
├── 📄 update_report.json    # Relatório gerado após execuções
├── 📄 README.md             # Documentação
├── 📄 LICENSE               # Licença MIT
└── 📁 downloads/            # Seus arquivos .zip ficam aqui
```

---

## 🤝 Contribuindo

Contribuições, issues e solicitações de recursos são bem-vindos!

1.  **Fork** o projeto.
2.  Crie uma branch para sua feature (`git checkout -b feature/NovaFuncionalidade`).
3.  Commit suas mudanças (`git commit -m 'Add: NovaFuncionalidade'`).
4.  Push para a branch (`git push origin feature/NovaFuncionalidade`).
5.  Abra um **Pull Request**.

### 🐛 Reportar Bugs
Ao relatar um bug, inclua:
- Versão do Python.
- Comando utilizado.
- Log de erro (`--verbose --log log.txt`).

---

## 📄 Licença

Este projeto é distribuído sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

```
Copyright (c) 2024 yanhenrique-dev
```

---

## 📊 Estatísticas

<div align="center">

![GitHub stars](https://img.shields.io/github/stars/yanhenrique-dev/GithubRepo-sync?style=social)
![GitHub forks](https://img.shields.io/github/forks/yanhenrique-dev/GithubRepo-sync?style=social)
![GitHub watchers](https://img.shields.io/github/watchers/yanhenrique-dev/GithubRepo-sync?style=social)

![GitHub Repo stars](https://img.shields.io/github/stars/yanhenrique-dev/GithubRepo-sync?style=flat-square)
![GitHub top language](https://img.shields.io/github/languages/top/yanhenrique-dev/GithubRepo-sync?style=flat-square&color=blue)
![GitHub repo size](https://img.shields.io/github/repo-size/yanhenrique-dev/GithubRepo-sync?style=flat-square)

### ⭐ Histórico de Estrelas

![Star History Chart](https://api.star-history.com/svg?repos=yanhenrique-dev/GithubRepo-sync&type=Date)

</div>

---

## 🌟 Agradecimentos

- **[Rich](https://github.com/Textualize/rich)** - Por tornar o terminal bonito e funcional.
- **[GitHub API](https://docs.github.com/en/rest)** - Pela robustez dos dados fornecidos.
- **[Python](https://www.python.org/)** - Pela simplicidade e poder da linguagem.

---

<div align="center">

### 🚀 Feito com ❤️ e Python

[![Typing SVG](https://readme-typing-svg.demolab.com?font=Fira+Code&size=20&duration=2000&pause=500&color=FF6B6B&center=true&vCenter=true&width=450&lines=Star+⭐+se+gostou!;Fork+🍴+e+contribua!;Share+📤+com+amigos!)](https://git.io/typing-svg)

![Visitor Count](https://profile-counter.glitch.me/yanhenrique-dev/GithubRepo-sync/count.svg)

</div>
