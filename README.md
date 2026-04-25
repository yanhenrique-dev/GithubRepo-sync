# 🚀 Update Repos - Atualizador de Repositórios GitHub

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=22&duration=3000&pause=1000&color=00D9FF&center=true&vCenter=true&width=600&lines=Atualize+seus+reposit%C3%B3rios+GitHub+automaticamente!;Interface+Rich+interativa+e+colorida!;Downloads+paralelos+com+barra+de+progresso!;Cache+inteligente+e+rate+limit+tratado!" alt="Typing SVG" />

</div>

---

## 📋 Índice

- [🎯 Sobre o Projeto](#-sobre-o-projeto)
- [✨ Funcionalidades](#-funcionalidades)
- [🎬 Demonstração](#-demonstração)
- [📦 Instalação](#-instalação)
- [🚀 Como Usar](#-como-usar)
- [⚙️ Configuração](#️-configuração)
- [📖 Exemplos](#-exemplos)
- [🤝 Contribuindo](#-contribuindo)
- [📄 Licença](#-licença)

---

## 🎯 Sobre o Projeto

O **Update Repos** é uma ferramenta poderosa em Python para manter seus arquivos ZIP de repositórios GitHub sempre atualizados. Com uma interface moderna (usando Rich) ou fallback para terminal simples, ele verifica, baixa e gerencia atualizações de múltiplos repositórios com facilidade.

### 🎨 Interface Rico (Rich)
- Tabelas coloridas e estilizadas
- Barra de progresso em tempo real
- Menu interativo para seleção de repositórios
- Cores e ícones para status

### ⚡ Performance
- Downloads paralelos (até 4 workers)
- Cache inteligente de API (evita rate limit)
- Retry automático em falhas
- Verificação assíncrona de repositórios

---

## ✨ Funcionalidades

| Funcionalidade | Descrição | Status |
|:---|:---|:---:|
| 🔍 **Verificação Inteligente** | Compara datas locais vs remotas | ✅ |
| 📥 **Downloads Paralelos** | Até 4 downloads simultâneos | ✅ |
| 🎨 **Interface Rich** | Tabelas, cores, progresso visual | ✅ |
| 🔐 **Autenticação** | Suporte a GitHub Tokens | ✅ |
| 💾 **Cache de API** | Evita rate limits do GitHub | ✅ |
| 🎯 **Seleção Interativa** | Escolha quais repos atualizar | ✅ |
| 📊 **Relatório JSON** | Log estruturado de operações | ✅ |
| 🚫 **Filtros** | `--repos` e `--skip` | ✅ |
| 🔄 **Retry Automático** | 3 tentativas em falhas | ✅ |
| 📝 **Verificação MD5** | Integridade dos downloads | ✅ |

---

## 🎬 Demonstração

### Interface Rich (se instalado)
```bash
pip install rich
python update_repos.py
```

<div align="center">

### 📺 Preview da Interface

```
╭─ GitHub Repo Updater ───────────────────────────────────────╮
│ update_repos v2.1                                          │
│ Diretório: /home/yan/Documentos/Code/Salvos do Github     │
│ Token: ✗  Workers: 4                                      │
╰──────────────────────────────────────────────────────────────╯

─── Verificando repositórios ────────────────────────────────
Consultando API...  [████████████████████] 17/17

┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ # ┃ Arquivo                   ┃ Repositório               ┃ Status       ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 1 │ claw-code-main.zip        │ ultraworkers/claw-code   │ ⬆️  outdated │
│ 2 │ langflow-main.zip        │ langflow-ai/langflow     │ ⬆️  outdated │
│ 3 │ hermes-agent-main.zip    │ NousResearch/hermes...  │ ⬆️  outdated │
│ 4 │ openclaude-main.zip      │ Gitlawb/openclaude       │ ✅ up_to_date│
└───┴──────────────────────────┴──────────────────────────┴──────────────┘

✅ Atualizados: 14  ⬆️  Defasados/Novos: 3  ⚠️  Erros: 0
```

</div>

### Terminal Simples (fallback)
```bash
python update_repos.py --check-only
```

```
============================================================
update_repos v2.1 | dir: /home/yan/Documentos/Code/Salvos do Github
============================================================
  ↑ claw-code-main.zip (outdated)
  ↑ langflow-main.zip (outdated)
  ✓ openclaude-main.zip (up_to_date)
  ...
```

---

## 📦 Instalação

### 1️⃣ Clone o repositório
```bash
git clone https://github.com/seu-usuario/update-repos.git
cd update-repos
```

### 2️⃣ (Opcional) Instale o Rich para interface melhorada
```bash
pip install rich
```

### 3️⃣ Configure seu token GitHub (recomendado)
```bash
export GITHUB_TOKEN="ghp_seu_token_aqui"
```

> 💡 **Dica**: Sem token, você tem limite de 60 requisições/hora. Com token: 5000 requisições/hora!

---

## 🚀 Como Usar

### Verificação Simples
```bash
python update_repos.py --check-only
```

### Atualização Automática (sem perguntas)
```bash
python update_repos.py --auto
```

### Interface Interativa
```bash
python update_repos.py
```
> Use números para toggle, `a` para todos, `n` para nenhum, `Enter` para confirmar

---

## ⚙️ Configuração

### Arquivo `update_repos.json` (opcional)
```json
{
  "token": "ghp_...",
  "workers": 4,
  "auto": false
}
```

### Variáveis de Ambiente
| Variável | Descrição | Exemplo |
|:---|:---|:---|
| `GITHUB_TOKEN` | Token de autenticação | `ghp_xxxx` |
| `NO_COLOR` | Desativa cores | `1` |

---

## 📖 Exemplos

### Verificar repositórios específicos
```bash
python update_repos.py --repos "claw-code-main.zip,langflow-main.zip"
```

### Pular alguns repositórios
```bash
python update_repos.py --skip "flai-master.zip,opensquad-master.zip"
```

### Diretório personalizado
```bash
python update_repos.py --dir "/caminho/para/arquivos"
```

### Logging detalhado
```bash
python update_repos.py --verbose --log update.log
```

### Combinando opções
```bash
python update_repos.py --auto --workers 8 --repos "claw-code-main.zip" --token "ghp_xxx"
```

---

## 🗂️ Estrutura do Projeto

```
update-repos/
├── 📄 update_repos.py      # Script principal
├── 📄 README.md            # Esta documentação
├── 📄 update_repos.json    # Configuração (opcional)
├── 📄 .repo_cache.json     # Cache da API (auto-gerado)
├── 📄 update_report.json   # Relatório de downloads (auto-gerado)
└── 📁 downloads/           # Seus ZIPs aqui
```

---


## 🤝 Contribuindo

@yanhenrique-dev 

### Como contribuir:
1. Fork o projeto
2. Crie sua branch (`git checkout -b feature/AmazingFeature`)
3. Commit suas mudanças (`git commit -m 'Add: AmazingFeature'`)
4. Push para a branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

### 🐛 Reportar Bugs
Abra uma [issue](https://github.com/seu-usuario/update-repos/issues) com:
- Descrição do problema
- Passos para reproduzir
- Logs (use `--verbose --log log.txt`)

---

## 📊 Estatísticas

<div align="center">

![GitHub language count](https://img.shields.io/github/languages/count/anomalyco/GithubRepo-sync?style=flat-square)
![GitHub top language](https://img.shields.io/github/languages/top/anomalyco/GithubRepo-sync?style=flat-square&color=blue)
![GitHub repo size](https://img.shields.io/github/repo-size/anomalyco/GithubRepo-sync?style=flat-square)
![GitHub downloads](https://img.shields.io/github/downloads/anomalyco/GithubRepo-sync/total?style=flat-square&color=green)

### ⭐ Histórico de Estrelas

![Star History Chart](https://api.star-history.com/svg?repos=yanhenrique-dev/GithubRepo-sync&type=Date)

</div>

---

## 📄 Licença

Distribuído sob a licença MIT. Veja `LICENSE` para mais informações.

```
MIT License

Copyright (c) 2026 Update Repos Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
```

---

## 🌟 Agradecimentos

- [Rich](https://github.com/Textualize/rich) - Interface terminal incrível
- [GitHub API](https://docs.github.com/en/rest) - Dados dos repositórios
- [Python](https://www.python.org/) - Linguagem poderosa

---

<div align="center">

### 🚀 Feito com ❤️ e Python

[![Typing SVG](https://readme-typing-svg.demolab.com?font=Fira+Code&size=18&duration=2000&pause=500&color=FF6B6B&center=true&vCenter=true&width=435&lines=Star+⭐+se+gostou!;Fork+🍴+e+contribua!;Share+📤+com+amigos!)](https://git.io/typing-svg)

![Visitor Count](https://profile-counter.glitch.me/yanhenrique-dev/GithubRepo-sync/count.svg)

</div>
