🚀 Update Repos — Atualizador Inteligente de Repositórios GitHub
<p align="center"> <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=22&duration=3000&pause=1000&color=00D9FF&center=true&vCenter=true&width=600&lines=Automatize+atualiza%C3%A7%C3%A3o+de+reposit%C3%B3rios+GitHub;Downloads+paralelos+com+alta+performance;Interface+moderna+com+Rich;Cache+inteligente+anti+rate+limit" /> </p>
🎯 Visão Geral

O Update Repos é uma ferramenta em Python criada para automatizar a verificação e atualização de arquivos ZIP de repositórios do GitHub.

Ele compara versões locais com remotas, identifica mudanças e baixa apenas o necessário.

⚡ Destaques
🔍 Detecção Inteligente
Compara timestamps locais vs GitHub
⚡ Downloads Paralelos
Até 4 workers simultâneos
🎨 Interface Rich
Visual moderno com tabelas e progresso
🧠 Cache Inteligente
Evita rate limit da API
🔐 Token GitHub
Até 5000 req/hora
🔄 Retry Automático
3 tentativas em falhas
🧪 Verificação MD5
Integridade dos downloads
📊 Relatórios JSON
Log completo das execuções
🖥️ Interface
🎨 Modo Rich
╭─ GitHub Repo Updater ───────────────────────────────╮
│ update_repos v2.1                                   │
│ Diretório: ~/repos                                  │
│ Token: ✓   Workers: 4                               │
╰─────────────────────────────────────────────────────╯
📦 Instalação
git clone https://github.com/yanhenrique-dev/GithubRepo-sync.git
cd GithubRepo-sync
Opcional (interface bonita)
pip install rich
Token GitHub
export GITHUB_TOKEN="ghp_seu_token"
🚀 Uso
python update_repos.py --check-only
python update_repos.py --auto
python update_repos.py
⚙️ Configuração
{
  "token": "ghp_xxx",
  "workers": 4,
  "auto": false
}
📂 Estrutura
GithubRepo-sync/
├── update_repos.py
├── update_repos.json
├── .repo_cache.json
├── update_report.json
└── downloads/
🤝 Contribuindo

Repositório oficial:
👉 https://github.com/yanhenrique-dev/GithubRepo-sync

Passos:
Fork
Branch (feature/...)
Commit
Push
Pull Request
🐛 Issues

Reporte bugs aqui:
👉 https://github.com/yanhenrique-dev/GithubRepo-sync/issues

Inclua:

Descrição
Passos
Logs (--verbose)
📊 Estatísticas
<p align="center"> <img src="https://img.shields.io/github/languages/count/yanhenrique-dev/GithubRepo-sync?style=flat-square" /> <img src="https://img.shields.io/github/languages/top/yanhenrique-dev/GithubRepo-sync?style=flat-square" /> <img src="https://img.shields.io/github/repo-size/yanhenrique-dev/GithubRepo-sync?style=flat-square" /> <img src="https://img.shields.io/github/downloads/yanhenrique-dev/GithubRepo-sync/total?style=flat-square&color=green" /> </p>
⭐ Star History
<p align="center"> <img src="https://api.star-history.com/svg?repos=yanhenrique-dev/GithubRepo-sync&type=Date" /> </p>
📄 Licença

MIT License

💡 Créditos
Rich
GitHub API
Python
🚀 Apoie

Se te ajudou:

⭐ Star
🍴 Fork
📤 Compartilha

Ou segue ignorando e baixando ZIP manualmente, que também é um estilo de vida.
