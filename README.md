# Agenda Semanal · GinásioTV

Página para gerar os posts "Agenda Semanal" do Ginásio Clube Olhanense para o Instagram
(1080x1350), a partir do calendário da FPB.

## Como usar

1. Abrir a página (GitHub Pages).
2. Escolher **De** / **Até** e carregar em **Gerar**.
3. Descarregar cada imagem ou todas de uma vez.

Eventos que não estão na FPB (ex.: convívios de minis) adicionam-se em **Eventos manuais**.
Ficam guardados no browser de quem os adiciona.

## Como funciona

- `.github/workflows/update-games.yml` corre `fetch_games.py` às 07:00 e 17:00 UTC
  (e quando se carrega em **Run workflow** no separador *Actions*). Lê a FPB com Firefox e
  grava `games.json` com os nomes já formatados.
- `index.html` lê `games.json` e desenha os posts no browser.
- Nomes abreviados de adversários e pavilhões: `agenda_config.json` → `team_aliases` / `venue_aliases`.
  Depois de alterar, correr o workflow para atualizar `games.json`.

`scrapeData.py` e `agenda_post.py` são cópias dos ficheiros do sincronizador GinásioTV.
