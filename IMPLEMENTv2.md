# IMPLEMENTv2 — Correções e Reformulação de UI

## Problema 1: Diálogo de Consent muito estreito
**Arquivo:** `src/big_parental_controls/ui/compliance.py`
**Causa:** `AdwAlertDialog` tem largura padrão estreita para textos longos.
**Solução:** Usar `dialog.set_content_width(480)` e `dialog.set_content_height(520)` para dar mais espaço ao texto de consentimento. O `AdwAlertDialog` herda de `AdwDialog` que suporta esses métodos.

---

## Problema 2: Gráficos de Activity não intuitivos
**Arquivos:**
- `src/big_parental_controls/ui/widgets/activity_block.py` — reescrever
- `src/big_parental_controls/ui/widgets/usage_chart.py` — reescrever
- `src/big_parental_controls/services/activity_service.py` — adicionar `get_daily_hourly()`

**Problemas atuais:**
1. O gráfico diário mostra 7 barras sem possibilidade de selecionar um dia
2. O heatmap horário agrega TODOS os dias, sem indicar qual período
3. Não há seletor de dia nem navegação temporal
4. Os valores no gráfico são confusos (números sem unidade)

**Solução — Estado da arte (inspirado em Apple Screen Time / Google Family Link):**

### Layout novo:
```
┌─────────────────────────────────────────────┐
│  Activity                                   │
│  Usage data from session history            │
│                                             │
│  ◂  Seg  Ter  Qua  Qui  Sex  Sáb [Dom]  ▸  │  ← Week nav + day selector
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  Total: 2h 35min                    │    │  ← Summary for selected day
│  └─────────────────────────────────────┘    │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  █     █████  ██████               │    │  ← Hourly bars for SELECTED day
│  │  00  03  06  09  12  15  18  21    │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  ● 00:09 — 04:13  (4h 4min)       │    │  ← Sessions for selected day
│  │    Graphical session                │    │     (merged, typed correctly)
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### Implementação:
1. **`ActivityService.get_daily_hourly(username, date)`** — retorna distribuição horária [0..23] para UM dia específico
2. **`DaySelector` widget** — faixa de 7 botões (Seg-Dom) com navegação por semana (setas)
3. **`DailySummaryRow`** — Adw.ActionRow com total do dia
4. **`HourlyBarChart`** — gráfico de barras verticais, 24 colunas, para o dia selecionado
5. Ao clicar num dia, atualiza gráfico horário + sessões filtradas

### Detalhes:
- Gráfico diário removido (substituído pelo seletor de dias que já mostra visualmente quais dias tiveram uso)
- Gráfico horário agora é POR DIA (não agregado)
- Valores com unidade: "35 min" acima de cada barra
- Cores: Adwaita accent, destaque no dia selecionado ndo DaySelector

---

## Problema 3: Sessions TTY incorretas
**Arquivo:** `src/big_parental_controls/services/activity_service.py`

**Causa:** O sistema usa SDDM + Wayland em ttyN. Quando rafael faz login gráfico, o SDDM aloca
tty2, tty3, tty5, tty7 etc. para sessões gráficas. O código classifica tudo em ttyN como "tty",
mas na verdade são sessões gráficas (KDE Plasma/Wayland).

**Evidência do journal:**
```
rafael: TTY=tty3; COMMAND=/usr/bin/biglinux-backlight-restore
kded6 carregado em /home/rafael/
xsettingsd carregado
```
Todas as sessões ttyN de rafael são graphical.

**Solução:**
1. **Detectar sessão gráfica corretamente:**
   - `pts/X :display` → "Graphical terminal" (terminal dentro da sessão gráfica)
   - `ttyN` em sistema com SDDM → "Graphical session" (display manager login)
   - A heurística: se o sistema tem display manager (`/run/sddm.pid` ou similar), todos os `ttyN` são graphical
   - Alternativamente: checar se o tty está no seat0 via `loginctl`

2. **Mesclar sessões sobrepostas em "períodos de uso":**
   - Se rafael tem tty2 00:09-00:40 e pts/0 00:10-00:30 → mostrar como um único período "00:09 — 00:40"
   - Isso é mais intuitivo: mostra quando o computador foi REALMENTE usado

3. **Classificação simplificada:**
   - "Graphical session" (ícone video-display) para ttyN e pts com display
   - "Remote session" (ícone network) para pts sem display
   - Não mostrar "tty" como tipo (confuso para pais)

---

## Problema 4: DNS via nftables (não systemd-resolved)
**Arquivos:**
- `src/big_parental_controls/ui/pages/dns_page.py` — remover banner systemd-resolved
- `src/big_parental_controls/services/dns_service.py` — implementar aplicação via nftables

**Causa:** O banner diz "DNS filtering requires systemd-resolved" mas a abordagem correta é redirecionar
DNS transparentemente via nftables, usando match por UID do owner.

**Solução:**
1. **Remover banner de systemd-resolved**
2. **Adicionar banner explicativo correto:**
   "DNS queries from supervised users will be transparently redirected to family-safe servers."
3. **Implementar `_apply_nftables_rule(uid, dns_ip)`** no serviço DNS:
   ```bash
   # Criar tabela e chain se não existem
   nft add table ip big_parental
   nft add chain ip big_parental dns_redirect { type nat hook output priority -100 \; }
   
   # Regra por UID: redirecionar DNS (udp 53) para servidor seguro
   nft add rule ip big_parental dns_redirect meta skuid <UID> udp dport 53 dnat to <DNS_IP>
   nft add rule ip big_parental dns_redirect meta skuid <UID> tcp dport 53 dnat to <DNS_IP>
   ```
4. **Para desativar:** remover regras do UID
5. **Executar via pkexec** (precisa root para nftables)
6. **Persistência:** salvar config e reaplicar no boot via systemd service do daemon

---

## Problema 5: StatusPage com scroll interna na tela inicial
**Arquivo:** `src/big_parental_controls/ui/pages/main_view.py`

**Causa:** O `AdwStatusPage` ocupa muito espaço vertical e pode estar causando problemas de
layout dentro do `ScrolledWindow`. O ícone e texto ficam cortados, exibindo scroll interno.

**Solução:** Substituir `AdwStatusPage` por um widget mais compacto:
- `Gtk.Image` com o ícone (48px)
- `Gtk.Label` com o título (markup bold, tamanho grande)
- `Gtk.Label` com a descrição (dim-label)
- Tudo dentro de um `Gtk.Box` vertical com alinhamento central

Isso elimina o comportamento de scroll interno do StatusPage e dá controle total do layout.

---

## Ordem de implementação:
1. Largura do consent dialog (1 linha)
2. StatusPage → Header compacto (main_view.py)
3. Session type detection (activity_service.py)
4. Activity charts redesign (activity_block.py + usage_chart.py)
5. DNS nftables (dns_page.py + dns_service.py)
6. Deploy + validação na VM
