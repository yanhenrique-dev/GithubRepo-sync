# STYLEGUIDE — RepoRefresh

Replicação do sistema de design do **OpenCode Console** (`opencode.ai/console`).

**Fonte de verdade:** `~/Downloads/opencode.ai/console/assets/index-Be-vq2Mk.css`
(+ `badge-v2`, `segmented-control-v2`, `drawer`, `page-shell`, `inline-input-v2`, `admin-tabs`).
Nenhum valor foi inventado. Se não está no CSS-fonte, não está aqui.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `static/tokens.css` | Rampas, alfa, cores de estado, semânticos light/dark, elevação, raios, tipografia, movimento |
| `static/components.css` | Primitives com `data-component` / `data-slot` |
| `static/shell.css` | Grid do app, sidebar, header, page shell, as três telas |
| `STYLEGUIDE.md` | Este documento |

Ordem de carga no HTML: `tokens.css` → `components.css` → `shell.css`.

## Convenção de atributos

Todo primitive é identificado por atributo, nunca por classe utilitária:

```html
<button data-component="button-v2" data-variant="contrast" data-size="normal" disabled>
  <svg class="icon" data-slot="icon"><use href="#i-scan"></use></svg>
  <span>Escanear</span>
</button>
```

- `data-component` — o primitive (`button-v2`, `text-input-v2`, `tag`, …)
- `data-slot` — a parte dentro dele (`icon`, `text-input-v2-input`, `label`, …)
- `data-variant` — `neutral` · `contrast` · `outline` · `ghost` · `ghost-muted` · `danger` · `warning` · `loading`
- `data-size` — `small` (20–24px) · `normal` (24–28px) · `large` (32px)
- `data-state` — `hover` · `pressed` · `focus` · `disabled` · `closed` · `loading`
- Switch usa `data-console-toggle-size="md"` (nome do console, não `data-size`)

Estados de interação são dirigidos por `:hover` **e** por `[data-state=…]`, como no console.

## Tokens semânticos

| Token | Light | Dark |
|---|---|---|
| `--v2-background-bg-base` | `#fff` | `#161616` |
| `--v2-background-bg-deep` | `#fafafa` | `#080808` |
| `--v2-background-bg-layer-01` | `#fafafa` | `#242424` |
| `--v2-background-bg-layer-02` | `#f2f2f2` | `#2e2e2e` |
| `--v2-background-bg-layer-03` | `#eee` | `#3a3a3a` |
| `--v2-background-bg-layer-04` | `#dbdbdb` | `#5c5c5c` |
| `--v2-background-bg-contrast` | `#242424` | `#5c5c5c` |
| `--v2-background-bg-button-neutral` | `#fff` | `rgba(255,255,255,.06)` |
| `--v2-background-bg-accent` | `#3b5cf6` | `#3b5cf6` |
| `--v2-text-text-base` | `#161616` | `#fafafa` |
| `--v2-text-text-muted` | `#5c5c5c` | `#aeaeae` |
| `--v2-text-text-faint` | `#808080` | `#808080` |
| `--v2-text-text-accent` | `#3b5cf6` | `#a2bcff` |
| `--v2-icon-icon-base` | `#3a3a3a` | `#dbdbdb` |
| `--v2-icon-icon-muted` | `#808080` | `#808080` |
| `--v2-border-border-muted` | `rgba(0,0,0,.08)` | `rgba(255,255,255,.08)` |
| `--v2-border-border-base` | `rgba(0,0,0,.10)` | `rgba(255,255,255,.10)` |
| `--v2-border-border-strong` | `rgba(0,0,0,.20)` | `rgba(255,255,255,.20)` |
| `--v2-border-border-focus` | `#7698fd` | `#7698fd` |
| `--v2-overlay-simple-overlay-hover` | `rgba(0,0,0,.04)` | `rgba(255,255,255,.06)` |
| `--v2-overlay-simple-overlay-pressed` | `rgba(0,0,0,.08)` | `rgba(255,255,255,.10)` |
| `--v2-overlay-simple-overlay-scrim` | `rgba(0,0,0,.4)` | `rgba(0,0,0,.6)` |
| `--v2-state-bg-success` / `fg` | `#e7f9ea` / `#198b43` | `#14361d` / `#6bd586` |
| `--v2-state-bg-warning` / `fg` | `#fefaec` / `#cb9f34` | `#4b4025` / `#f2cf76` |
| `--v2-state-bg-danger` / `fg` | `#fceceb` / `#b82d35` | `#461516` / `#f17471` |
| `--v2-state-bg-info` / `fg` | `#ecf1fe` / `#2c47c8` | `#1b2852` / `#7698fd` |

O tema vive em `[data-color-scheme="light" | "dark"]` no `<html>`. Um script inline
antes da primeira pintura lê `localStorage["alldown.theme"]` e cai para
`prefers-color-scheme` — não há flash.

## Elevação

A "borda" é uma camada de sombra de `.5px`, **nunca** `border: 1px`. É o que dá o ar de produto nativo.

| Token | Light | Dark |
|---|---|---|
| `--v2-elevation-raised` | `0 2px 4px rgba(0,0,0,.04), 0 1px 2px -1px rgba(0,0,0,.08), 0 0 0 .5px rgba(0,0,0,.12)` | `0 2px 4px rgba(0,0,0,.30), 0 1px 2px rgba(0,0,0,.30), 0 0 0 .5px rgba(255,255,255,.16), 0 -.5px 0 rgba(255,255,255,.06)` |
| `--v2-elevation-floating` | idem, `0 8px 16px` / `0 4px 8px` | idem, `0 8px 16px` / `0 4px 8px` |
| `--v2-elevation-overlay` | idem, `0 16px 32px` / `0 8px 16px` | idem, `0 16px 32px` / `0 8px 16px` |
| `--v2-elevation-button-neutral` | `0 1px 1.5px rgba(0,0,0,.10), 0 0 0 .5px rgba(0,0,0,.14)` | `0 1px 2px rgba(0,0,0,.40), 0 0 0 .5px rgba(255,255,255,.20), 0 -.5px 0 rgba(255,255,255,.10)` |
| `--v2-elevation-elements` | `0 .5px .5px rgba(0,0,0,.40)` | idem |
| `--v2-elevation-switch-off` / `-on` | inset shadows | inset shadows |

Card comum nunca passa de `--elev-raised`.

## Raios

| Elemento | Token | Valor |
|---|---|---|
| tag / badge / código | `--v2-radius-tag` | `2px` |
| menu item, tooltip, avatar pequeno, botão `small` | `--v2-radius-control` | `4px` |
| botão, input, select, segmented control | `--v2-radius-input` | `6px` |
| toast, card | `--v2-radius-surface` | `8px` |
| dialog, command palette | `--v2-radius-overlay` | `12px` |
| scrollbar thumb, avatar, switch | `--v2-radius-pill` | `9999px` |

## Tipografia

Inter. `font-display: swap`, `font-synthesis: none`, `tabular-nums` em todo número.

> Os arquivos em `static/fonts/` são instâncias **estáticas** do Inter (sem tabela `fvar`).
> Cada peso do console é declarado em `@font-face` e servido pela instância do mesmo grau
> óptico, para que nenhuma declaração `font-weight` fora de **440 / 530 / 610** exista no projeto.

| Uso | size / line-height | weight | tracking |
|---|---|---|---|
| label, botão, item de menu, nav | `13px / 20px` | `530` | `-0.04px` |
| input, select, segmented control | `13px / 16px` | `440` | `-0.04px` |
| título de dialog / h1 | `15px / 20px` | `530` | `-0.13px` |
| tag, badge, tooltip, avatar, footnote | `11px / 1` | `530` | `+0.05px` |
| texto corrido | `13px / 20px` | `440` | `-0.04px` |
| valor de stat card | `24px / 28px` | `610` | `-0.4px` |

Hierarquia é feita por **peso e cor**, nunca por tamanho grande. Não existe `text-4xl`
neste sistema. Monospace: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`.

## Componentes

| `data-component` | Tamanhos | Variantes |
|---|---|---|
| `button-v2` | `small` 24 · `normal` 28 · `large` 32 | `neutral` `contrast` `outline` `ghost` `ghost-muted` `danger` `warning` `loading` |
| `icon-button-v2` | `small` 20 · `normal` 24 · `large` 28 | `neutral` `contrast` `ghost` `ghost-muted` |
| `text-input-v2` | 28 (32 `large`) | — + `data-invalid` `data-disabled` `data-numeric` `data-leading-icon` |
| `textarea-v2` | `min-height: 80px`, `resize: vertical` | idem |
| `select-v2` | 28 | idem |
| `checkbox-v2` | `16×16`, raio `4px` | `data-checked` `data-invalid` `data-disabled` |
| `switch` | `data-console-toggle-size="md"` → 32×20, thumb 16 | `data-checked` |
| `tag` | `16px`, raio `2px` | `accent` `success` `warning` `danger` `info` `mono` + `data-high-contrast` |
| `segmented-control-v2` | 28, `box-shadow: 0 0 0 .5px` | `data-pressed` no item |
| `avatar-v2` | 16 / 20 / 24 / 28 | `data-tone` = 10 cores + `data-kind="org"` |
| `tooltip-v2` | `5px 6px`, raio `4px`, 11/12 | — |
| `toast-v2` | 320px, raio `8px`, grid `1fr 20px` | `data-tone` |
| `drawer` | `min(100vw, 40rem)` | `data-closed` no painel |
| `dialog-v2` | 480 (`large` 640), raio `12px` | `data-size` |
| `data-table` | header 32 · row 40 | `data-align="end"` + `tabular-nums` |
| `card` | padding 16 (`large` 20) | `data-interactive` |
| `scroll-view` | thumb 4px, trilho 12px | `data-visible` |
| `progress-bar` | 4px | `data-variant` `data-state="indeterminate"` |
| `empty-state` / `skeleton` | — | `data-shape` no skeleton |
| `divider-v2` | `1px` com `scaleY(.5)` | `data-orientation` |
| `menu-v2-content` / `menu-v2-item` | item 28, raio `4px` | `data-checked` `data-highlighted` |
| `field-v2` / `inline-input-v2` / `loader-v2` | — | — |

## Movimento

| Ação | Duração / easing | Token |
|---|---|---|
| hover de botão / campo | `85ms ease-out` | `--v2-motion-control` |
| segmented control | `120ms ease` | `--v2-motion-segmented` |
| checkbox / switch | `170ms ease-out` | `--v2-motion-check` |
| tooltip / menu | `120ms ease-out` | `--v2-motion-tooltip` |
| scrollbar thumb | `150ms ease` / `200ms ease` opacidade | `--v2-motion-thumb` |
| fade de overlay | `160ms ease-out` | `--v2-motion-overlay` |
| drawer | `180ms cubic-bezier(.2,.8,.2,1)` in · `120ms ease-in` out | `--v2-motion-drawer-*` |
| toast | `280ms cubic-bezier(.2,0,0,1)` transform · `160ms` opacidade | `--v2-motion-toast` |

`@media (prefers-reduced-motion: reduce)` corta toda animação e transição.

## Layout

```
┌──────────────────────────────────────────────┐
│ header  h 48px · bg-base · .5px embaixo      │  sticky
├────────────┬─────────────────────────────────┤
│ sidebar    │ main                            │
│ w 232px    │ padding 24px 32px               │
│ bg-base    │ max-width 1200px                │
│ .5px dir.  │  breadcrumb (11px faint)         │
│ nav item   │  h1 15px/20px w530               │
│ h 28px     │  descrição 13px muted            │
│ raio 4px   │  cards grid gap 16px            │
│ gap 2px    │                                 │
└────────────┴─────────────────────────────────┘
```

`html` é `--bg-deep`, `body` é `--bg-base`. Sem gradiente de fundo em página.

- `<1024px` — sidebar vira rail de `72px` (só ícones)
- `<768px` — sidebar vira off-canvas, `topbar__menu` aparece
- Cards: `repeat(auto-fit, minmax(180px, 1fr))`, `gap: 12px`, `min-height: 88px`
- Densidade alta: o shell cabe sem scroll em 900px de altura

## Scrollbar

O console esconde a scrollbar nativa e desenha a dele. O mesmo vale aqui
(`[data-component=scroll-view]` + `[data-slot=scroll-view-thumb]`, controlado por
`initScrollThumb()` em `app.js`): trilho de `12px`, thumb de `4px`, `border-radius: 9999px`,
`backdrop-filter: blur(4px)`, opacidade `0 → 1` em `200ms`, `border-muted → border-strong` em `150ms`.

## Regras absolutas cumpridas

1. Sem gradiente decorativo — só o `180deg` branco `2%→0%` de superfície e o gradiente horizontal de overlay.
2. Sem sombra grande em card comum (máx. `--elev-raised`).
3. Sem `border: 1px` em superfície — `.5px` via `box-shadow`.
4. Sem emoji, ilustração ou ícone 3D. Ícone = SVG `16px`, stroke `1.5`, `currentColor`.
5. Sem cor fora da rampa. Azul só via `--v2-blue-*` / `--v2-text-text-accent`.
6. Sem `text-4xl` / `text-5xl`.
7. Sem `rounded-xl` / `rounded-2xl` em card (máx. `8px`; `12px` só em overlay).
8. Sem `transition: all`.
9. Sem `text-shadow` (exceto o `none` explícito do botão).
10. Sem gradiente de fundo em página.
11. Toda tabela numérica alinhada à direita com `tabular-nums`.
12. Zero estilo inline, zero `any`, só tokens nos valores.

`@media (forced-colors: active)` é a única exceção à regra 3: troca as bordas de 1px porque
o Windows High Contrast descarta sombras.

## Verificação

```bash
node --check static/app.js        # sintaxe
.venv/bin/python -m pytest tests/ -q
uvx --from ruff==0.16.8 ruff check app.py core tray.py
```

Para conferir um primitive isolado, monte o markup do `STYLEGUIDE.md` num `.html`
deixe-preto apontando para os três CSS — nenhum componente depende de JavaScript.
