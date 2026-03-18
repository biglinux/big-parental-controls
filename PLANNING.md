# PLANNING.md — Big Parental Controls: Plano de Evolução

> Plano de aprimoramentos para o projeto `big-parental-controls`
> Última atualização: 2026-03-17

---

## Sumário Executivo

Este documento detalha o plano de implementação de **monitoramento de uso**, **gráficos de atividade** e **conformidade com legislação de proteção digital** para o Big Parental Controls. O foco é:

1. **Coleta de dados de uso** via `journalctl`, `systemd-logind`, `wtmp` e daemon Rust com /proc polling
2. **Gráficos nativos GTK4** exibindo horários de uso, programas utilizados e duração por usuário
3. **Conformidade legal** com ECA Digital (Lei 15.211/2025), UK Children's Code e EU Digital Services Act

---

## Estado Atual do Sistema (verificado na VM 192.168.1.31)

### Recursos disponíveis

| Recurso | Estado | Versão/Info |
|---------|--------|-------------|
| `systemd/journalctl` | ✅ Instalado | 259.1-1 (+PAM) |
| `last` / `wtmp` | ✅ Funcional | Dados desde 2026-03-16 |
| `/proc` filesystem | ✅ Sempre disponível | Polling leve via daemon Rust |
| `loginctl` / `systemd-logind` | ✅ Funcional | Logs de sessões por usuário |
| Python `cairo` (pycairo) | ✅ 1.29.0 | Para desenho de gráficos |
| GTK4 `Gdk` + `Gsk` | ✅ Funcional | Rendering nativo |
| `PangoCairo` | ✅ Funcional | Texto em Cairo |
| `matplotlib` / `plotly` | ❌ Não instalados | **Não necessários** — usaremos Cairo nativo |

### Usuários supervisionados ativos

| Usuário | UID | Grupo |
|---------|-----|-------|
| minibruno | 1002 | supervised |
| tata | 1003 | supervised |
| cassia | 1004 | supervised |
| rafael | 1005 | supervised |

---

## Fontes de Dados para Monitoramento

### 1. `systemd-logind` (journalctl)
**Disponível imediatamente** — dados de login/logout de todos os usuários.

```bash
# Sessões do usuário rafael
sudo journalctl -u systemd-logind --no-pager -o json |
  jq 'select(.MESSAGE | test("rafael|uid=1005"))'

# Sessões por UID
sudo journalctl _UID=1005 --since "7 days ago" -o json
```

**Dados extraíveis:**
- Início/fim de sessão (login/logout)
- Tipo de sessão (wayland, x11, tty)
- Duração total por dia

### 2. `wtmp` / `last`
**Disponível imediatamente** — histórico de logins compacto.

```bash
last -n 100 rafael --time-format iso
```

**Dados extraíveis:**
- Horários de login/logout por usuário
- Duração de cada sessão
- Terminal utilizado (tty, pts)

### 3. `systemd cgroup` / `systemd-cgls`
**Disponível imediatamente** — processos ativos por sessão.

```bash
# Processos do usuário no cgroup
systemd-cgls user.slice/user-1005.slice --no-pager
```

**Dados extraíveis:**
- Processos ativos na sessão atual
- Árvore de processos por usuário

### 4. `/proc` + polling (para apps ativos)
**Disponível imediatamente** — snapshot de processos leve e sem dependências.

A cada 1 minuto (via timer systemd existente), escanear `/proc` para capturar processos ativos de cada usuário supervisionado.

```python
import os

def get_user_processes(target_uid: int) -> list[dict]:
    """Scan /proc for processes owned by target_uid."""
    processes = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            stat = os.stat(f"/proc/{pid}")
            if stat.st_uid != target_uid:
                continue
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
            # Filter out kernel threads and system daemons
            if comm.startswith("kworker") or comm in ("systemd", "dbus-broker"):
                continue
            processes.append({"pid": int(pid), "comm": comm})
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    return processes
```

**Dados extraíveis:**
- Quais programas estão em execução (nome do processo)
- Frequência de uso (quantos scans o processo apareceu × intervalo)
- PID e hierarquia de processos

**Benefícios do /proc polling via daemon Rust:**
- Zero dependências extras — daemon já roda com tokio/zbus
- Zero overhead de kernel — apenas leitura de /proc
- Performance — Rust escaneia /proc em <1ms
- Respeita minimização de dados (Art. 13 ECA Digital)

---

## Arquitetura Proposta

### Redesign UX: Navegação Centrada no Usuário

**Problema da UI atual:** Sidebar com 6 categorias (Home, Users, Apps, Time, DNS, Help) obriga o administrador a navegar entre seções e selecionar o usuário em cada uma — alta carga cognitiva, muitos cliques, modelo mental fragmentado.

**Solução proposta:** Duas telas com lógica simples → "Escolher pessoa → Ver/configurar tudo sobre ela".

#### Tela Principal (MainView)

```
┌─────────────────────────────────────────────────────────────┐
│  [HeaderBar]                              [≡ Menu / Sobre]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🛡️  Controle Parental                                     │
│                                                             │
│  Proteja crianças neste computador. Tudo funciona           │
│  localmente, nenhum dado sai da máquina.                    │
│                                                             │
│  [ℹ️ Mais informações]   ← botão abre modal/dialog         │
│                                                             │
│  ┌─ Contas Supervisionadas ──────────────────────────────┐ │
│  │                                                        │ │
│  │  👤 Rafael       ● Online · 1h 20min hoje     [→]     │ │
│  │  👤 Mini Bruno   ○ Offline · Último: ontem    [→]     │ │
│  │  👤 Tata         ○ Offline · Último: 15/03    [→]     │ │
│  │  👤 Cassia       ○ Offline                    [→]     │ │
│  │                                                        │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  [+ Adicionar conta supervisionada]                         │
│                                                             │
│  ┌─ Ajuda ───────────────────────────────────────────────┐ │
│  │  CVV 188 · SaferNet · Disque 100 · CERT.br           │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─ Conformidade ────────────────────────────────────────┐ │
│  │  ECA Digital (Lei 15.211/2025) · LGPD (Lei 13.709)   │ │
│  │  · UK Children's Code · EU Digital Services Act       │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Componentes:**
- `AdwNavigationView` como container principal (push/pop de páginas)
- Primeira página: `AdwClamp` com `AdwPreferencesPage`
- Cada usuário é um `AdwActionRow` com avatar, badge de status e chevron `→`
- Botão "Mais informações" abre `AdwAlertDialog` com texto completo sobre o programa + leis
- Contatos de ajuda e compliance ficam na mesma tela (scroll)

#### Tela de Detalhes do Usuário (UserDetailView)

Ao clicar em um usuário, faz `navigation_view.push()` para a tela de detalhes:

```
┌─────────────────────────────────────────────────────────────┐
│  [← Voltar]        Rafael                    [≡ Menu]       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─ Resumo ──────────────────────────────────────────────┐ │
│  │  Status: ● Online agora                               │ │
│  │  Hoje: 1h 20min   Média semanal: 1h 45min             │ │
│  │  Perfil etário: Criança (< 10 anos)  [Alterar]        │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─ Horários Permitidos ─────────────────────────────────┐ │
│  │  ⬛ Habilitado                                         │ │
│  │  08:00 — 12:00                               [✕] [+]  │ │
│  │  14:00 — 18:00                               [✕] [+]  │ │
│  │  Limite diário: 3h                                     │ │
│  │                  [Aplicar]                              │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─ Atividade ───────────────────────────────────────────┐ │
│  │  [7d ▾]                                                │ │
│  │  ┌─ Uso Diário ────────────────────────────────────┐  │ │
│  │  │  ████ ████ ████ ████ ████ ████ ████             │  │ │
│  │  │  Seg  Ter  Qua  Qui  Sex  Sáb  Dom             │  │ │
│  │  └─────────────────────────────────────────────────┘  │ │
│  │                                                        │ │
│  │  ┌─ Horários de Uso ──────────────────────────────┐   │ │
│  │  │  [Heatmap 7×24]                                │   │ │
│  │  └────────────────────────────────────────────────┘   │ │
│  │                                                        │ │
│  │  ┌─ Apps Mais Usados ─────────────────────────────┐   │ │
│  │  │  🌐 Firefox .............. 2h 45min ██████████ │   │ │
│  │  │  🖥️ Konsole ............. 1h 20min ██████     │   │ │
│  │  │  📝 Kate .................   45min ████       │   │ │
│  │  └────────────────────────────────────────────────┘   │ │
│  │                                                        │ │
│  │  ┌─ Sessões Recentes ─────────────────────────────┐   │ │
│  │  │  17/03 00:52 — 01:16 (23 min) · wayland       │   │ │
│  │  │  16/03 23:58 — 00:09 (11 min) · wayland       │   │ │
│  │  └────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─ Apps Permitidos ─────────────────────────────────────┐ │
│  │  Lista de aplicativos com switches on/off              │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─ Filtro Web ──────────────────────────────────────────┐ │
│  │  DNS seguro: [Família ▾]                               │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─ Monitoramento de Apps ───────────────────────────────┐ │
│  │  ⬛ Rastrear apps usados (verifica a cada minuto)      │ │
│  │  Dados dos últimos 30 dias · excluir dados             │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─ Ações ───────────────────────────────────────────────┐ │
│  │  [Remover Supervisão]         [Excluir Conta]         │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ⓘ Dados de atividade ficam exclusivamente neste            │
│    computador. ECA Digital Art. 18 · LGPD Art. 14          │
└─────────────────────────────────────────────────────────────┘
```

**Vantagens da navegação centrada no usuário:**

| Aspecto | Antes (sidebar por categoria) | Depois (centrada no usuário) |
|---------|-------------------------------|------------------------------|
| Cliques para configurar tempo | Sidebar "Time" → dropdown usuário → config | Usuário → seção Horários |
| Modelo mental | "Em qual categoria estou?" | "O que quero mudar nesta pessoa?" |
| Contexto do usuário | Perdido ao trocar de seção | Sempre visível — é a própria página |
| Carga cognitiva | 6 categorias + dropdown | 1 lista → 1 detalhe |
| Consistência mobile | Split view colapsa | Push/pop natural |
| Visão geral | Não existe | MainView mostra status de todos |

#### Navegação técnica — `AdwNavigationView`

```python
# window.py — Nova estrutura
class MainWindow(Adw.ApplicationWindow):
    def __init__(self):
        self._nav_view = Adw.NavigationView()
        
        # Página principal (sempre na pilha)
        self._main_page = Adw.NavigationPage(
            title=_("Parental Controls"),
            child=MainView(),
        )
        self._nav_view.add(self._main_page)
    
    def show_user_detail(self, user):
        """Push user detail page onto navigation stack."""
        detail = UserDetailPage(user)
        page = Adw.NavigationPage(
            title=user.get_real_name() or user.get_user_name(),
            child=detail,
        )
        self._nav_view.push(page)
```

#### Estrutura de widgets da UserDetailPage

```python
class UserDetailPage(Gtk.Box):
    """All settings and activity for a single supervised user."""
    
    def __init__(self, user):
        # ScrolledWindow → Clamp(700) → VBox
        #   ├── SummaryGroup (AdwPreferencesGroup)
        #   │     ├── StatusRow (online/offline, tempo hoje)
        #   │     └── AgeProfileRow (perfil + botão alterar)
        #   │
        #   ├── TimeGroup (AdwPreferencesGroup)
        #   │     ├── EnableSwitch
        #   │     ├── TimeRangeRows (reutiliza lógica de time_limits_page)
        #   │     └── DailyLimitRow + ApplyButton
        #   │
        #   ├── ActivityGroup (AdwPreferencesGroup)
        #   │     ├── PeriodSelector (7d/30d)
        #   │     ├── DailyBarChart (Cairo widget)
        #   │     ├── HourlyHeatmap (Cairo widget)
        #   │     ├── AppUsageList (lista com barras)
        #   │     └── RecentSessionsList
        #   │
        #   ├── AppsGroup (reutiliza lógica de app_filter_page)
        #   │
        #   ├── DnsGroup (reutiliza lógica de dns_page)
        #   │
        #   ├── MonitoringGroup (AdwPreferencesGroup)
        #   │     ├── EnableSwitchRow — toggle monitoramento
        #   │     └── DataRetentionRow — info + delete
        #   │
        #   └── ActionsGroup (AdwPreferencesGroup)
        #         ├── RemoveSupervisionButton
        #         └── DeleteAccountButton
```

#### Componentes reutilizáveis

As páginas atuais (`time_limits_page.py`, `app_filter_page.py`, `dns_page.py`) contêm lógica de negócio misturada com construção de UI. Para a nova arquitetura:

1. **Extrair a lógica de construção de widgets** para funções/classes reutilizáveis
2. **`UserDetailPage` compõe** esses blocos dentro de uma única ScrolledWindow
3. **Serviços (`time_service`, `acl_service`, `dns_service`)** continuam inalterados

```python
# Exemplo: extrair bloco de time limits como widget reutilizável
class TimeLimitsBlock(Gtk.Box):
    """Time limits configuration block for embedding in UserDetailPage."""
    
    def __init__(self):
        # Mesma UI de TimeLimitsPage, mas como widget embedável
        # Sem ScrolledWindow próprio (o pai controla scroll)
    
    def set_user(self, user):
        """Load time limits for this user."""
```

#### Modal "Mais Informações"

```python
def _show_about_modal(self, button):
    """Show full program information in a dialog."""
    dialog = Adw.AlertDialog()
    dialog.set_heading(_("About Parental Controls"))
    dialog.set_body(
        _("BigLinux Parental Controls protects children on this computer.\n\n"
          "Features:\n"
          "• Supervised accounts with age-appropriate defaults\n"
          "• App and website filtering\n"
          "• Screen time limits\n"
          "• Activity monitoring with usage charts\n\n"
          "Privacy:\n"
          "All data stays on this device. Nothing is transmitted.\n\n"
          "Legal compliance:\n"
          "• ECA Digital — Law 15.211/2025 (Brazil)\n"
          "• LGPD — Law 13.709/2018 (Brazil)\n"
          "• UK Children's Code\n"
          "• EU Digital Services Act")
    )
    dialog.add_response("ok", _("OK"))
    dialog.present(self.get_root())
```

### Novos arquivos (ver Fase 0 para estrutura completa)

Os novos arquivos seguem a estrutura `src/big_parental_controls/` definida na Fase 0:

```
src/big_parental_controls/
  ui/
    main_view.py             # Tela principal: intro + lista de usuários
    user_detail_page.py      # Tela de detalhes do usuário (tudo junto)
    widgets/
      time_limits_block.py   # Bloco de horários (extraído de time_limits_page)
      app_filter_block.py    # Bloco de apps (extraído de app_filter_page)
      dns_block.py           # Bloco de DNS (extraído de dns_page)
      summary_block.py       # Bloco de resumo (status, perfil)
      activity_block.py      # Bloco de atividade (gráficos)
      monitoring_block.py    # Bloco de monitoramento (toggle, dados)
      usage_chart.py         # Widget Cairo para gráficos de barras/timeline
      app_usage_chart.py     # Widget Cairo para gráficos de uso de apps
      heatmap_chart.py       # Widget Cairo para heatmap hora/dia
  services/
    activity_service.py      # Coleta de dados de journalctl, wtmp
    daemon_client.py         # Cliente D-Bus para o daemon Rust
big-parental-daemon/
  src/
    main.rs                  # Entry: serve AgeSignal + ParentalMonitor1
    age_signal.rs            # Interface br.com.biglinux.AgeSignal
    monitor.rs               # Interface br.com.biglinux.ParentalMonitor1
    scanner.rs               # /proc polling loop
    storage.rs               # JSON atomic read/write
    desktop_map.rs           # Mapeamento processo → nome amigável
```

**Arquivos removidos (substituídos):**
- `welcome_page.py` → conteúdo migra para `main_view.py`
- `users_page.py` → lógica migra para `main_view.py` (lista) + `user_detail_page.py` (ações)
- `time_limits_page.py` → lógica migra para `widgets/time_limits_block.py`
- `app_filter_page.py` → lógica migra para `widgets/app_filter_block.py`
- `dns_page.py` → lógica migra para `widgets/dns_block.py`
- `support_page.py` → conteúdo migra para `main_view.py` (seção ajuda)
- `window.ui` → substituído por construção em Python (sem sidebar)

### Fluxo de dados

```
┌─────────────┐      ┌──────────────────┐      ┌───────────────────────┐
│  journalctl │─────▶│                  │      │                       │
│  wtmp/last  │─────▶│ activity_service │─────▶│  user_detail_page.py  │
└─────────────┘      │  (sessões Python)│      │  (blocos + gráficos)  │
                     └──────────────────┘      └───────────────────────┘
                                                         ▲
┌───────────────────────────┐                            │
│ big-parental-daemon       │   D-Bus (system bus)       │
│ (Rust, daemon unificado)  │────────────────────────────┘
│  ├→ AgeSignal interface   │         │
│  ├→ ParentalMonitor1 intf │         │
│  └→ snapshots JSON        │         ▼
└───────────────────────────┘   ┌──────────────────┐
                                │ Apps do usuário   │
                                │ (consultam        │
                                │  AgeSignal)       │
                                └──────────────────┘
```

---

## Fase 0: Reestruturação do Projeto (Prioridade: MÁXIMA — executar primeiro)

### 0.1 — Melhores práticas de implementação

Este é o **primeiro release** do programa. Não há compatibilidade com versões
anteriores para manter. Diretrizes:

- **Arquivos pequenos e focados** — cada arquivo tem uma única responsabilidade
- **UI separada de lógica** — código de interface nunca contém regras de negócio
- **Daemon separado de UI** — Rust para daemon, Python para interface GTK
- **Sem código morto** — se não é usado, não existe
- **Type hints em todos os métodos** — `def foo(self, user: str, days: int) -> list[dict]:`
- **Nomes semânticos** — variáveis e funções descrevem o que fazem
- **Sem dependências desnecessárias** — justificar cada nova dependência
- **Sem comentários óbvios** — código claro dispensa explicação
- **Erros explícitos** — tratar na fronteira do sistema, não em cada camada interna
- **i18n obrigatório** — todas as strings de UI em `_()`

### 0.2 — Migrar para `pyproject.toml` + estrutura `src/`

Seguindo o padrão do [ashyterm](/home/bruno/codigo-pacotes/ashyterm/), migrar de
scripts soltos em `usr/share/biglinux/` para uma estrutura de pacote Python padrão
com `pyproject.toml` e layout `src/`:

**Estrutura atual (legado):**
```
big-parental-controls/
  usr/share/biglinux/parental-controls/
    main.py
    app.py
    window.py
    pages/...
    services/...
    utils/...
```

**Nova estrutura (padrão Python):**
```
big-parental-controls/
  pyproject.toml                   # Metadados, deps, build-system
  default.nix                      # Nix build (portabilidade)
  flake.nix                        # Nix flake (dev shell + builds)
  DPIA.md                          # Avaliação de impacto (GDPR Art. 35)
  src/
    big_parental_controls/
      __init__.py                  # Versão, entry point main()
      __main__.py                  # sys.exit(main())
      app.py                       # GtkApplication lifecycle
      window.py                    # MainWindow (AdwNavigationView)
      ui/
        __init__.py
        main_view.py               # Tela principal: intro + lista de usuários
        user_detail_page.py        # Tela de detalhes do usuário
        widgets/
          __init__.py
          summary_block.py         # Status online, tempo hoje, perfil etário
          time_limits_block.py     # Horários permitidos + limite diário
          activity_block.py        # Gráficos + sessões recentes
          app_filter_block.py      # Apps permitidos (switches)
          dns_block.py             # Filtro DNS
          monitoring_block.py      # Toggle monitoramento + retenção
          usage_chart.py           # Widget Cairo: barras de uso diário
          app_usage_chart.py       # Widget Cairo: top apps por tempo
          heatmap_chart.py         # Widget Cairo: heatmap hora/dia
      services/
        __init__.py
        accounts_service.py        # Wrapper do AccountsService
        acl_service.py             # Bloqueio de binários via ACL
        activity_service.py        # Coleta de sessões (last/journalctl)
        daemon_client.py           # Cliente D-Bus para big-parental-daemon
        desktop_hide_service.py    # Esconder apps do menu
        dns_service.py             # Configuração DNS seguro
        malcontent_service.py      # OARS age ratings
        polkit_service.py          # Polkit helpers
        time_service.py            # pam_time + limites diários
      utils/
        __init__.py
        async_runner.py            # Thread-based async helper
        i18n.py                    # Gettext setup
      data/
        style.css                  # Estilos CSS do app
  big-parental-daemon/             # Daemon Rust (renomeado de big-age-signal/)
    Cargo.toml
    src/
      main.rs                      # Entry: tokio + zbus, serve 2 interfaces
      age_signal.rs                # Interface AgeSignal (D-Bus)
      monitor.rs                   # Interface ParentalMonitor1 (D-Bus)
      scanner.rs                   # /proc polling loop
      storage.rs                   # JSON read/write (atomic)
      desktop_map.rs               # Processo → nome amigável
  usr/
    bin/
      big-parental-controls        # Launcher script (compat)
      big-supervised-indicator     # Tray indicator
    lib/
      big-parental-controls/
        group-helper               # Privileged operations (pkexec)
      systemd/
        system/
          big-parental-daemon.service
    share/
      applications/
      dbus-1/
        system.d/
          br.com.biglinux.ParentalDaemon.conf  # Política D-Bus
      icons/
      polkit-1/
  locale/                          # .po files
  tests/                           # pytest
  pkgbuild/
    PKGBUILD
    big-parental-controls.install
  nix/                             # Nix helpers (se necessário)
```

### 0.3 — `pyproject.toml`

```toml
[project]
name = "big-parental-controls"
version = "1.0.0"
description = "Parental controls for BigLinux — local-only, privacy by design"
classifiers = [
    "Development Status :: 4 - Beta",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Topic :: Security",
]
authors = [
    { name = "Bruno Gonçalves", email = "bigbruno@gmail.com" },
]
license = "GPL-3.0-or-later"
license-files = ["COPYING"]
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "PyGObject",
    "pycairo",
]

[project.gui-scripts]
big-parental-controls = "big_parental_controls:main"

[project.urls]
Homepage = "https://github.com/biglinux/big-parental-controls"
Issues = "https://github.com/biglinux/big-parental-controls/issues"

[build-system]
requires = ["uv_build"]
build-backend = "uv_build"

[tool.ruff.lint]
select = ["E", "F", "W", "I"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

### 0.4 — `flake.nix` (portabilidade para outras distros)

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        packages = {
          default = self.packages.${system}.big-parental-controls;
          big-parental-controls = pkgs.callPackage ./. { inherit pkgs; };
        };
        devShells.default = pkgs.mkShell {
          inputsFrom = [ self.packages.${system}.default ];
          packages = with pkgs; [ uv cargo rustc rust-analyzer ];
          shellHook = ''
            export PYTHONPATH="$PWD/src:$PYTHONPATH"
          '';
        };
      }
    );
}
```

### 0.5 — `default.nix`

```nix
{
  pkgs,
  lib,
  python3Packages,
  gtk4,
  libadwaita,
  pkg-config,
  wrapGAppsHook4,
  gobject-introspection,
}:

python3Packages.buildPythonApplication {
  pname = "big-parental-controls";
  version = "1.0.0";

  src = ./.;
  pyproject = true;

  build-system = with python3Packages; [ uv-build ];
  dependencies = with python3Packages; [
    pygobject3
    pycairo
  ];

  nativeBuildInputs = [
    pkg-config
    wrapGAppsHook4
    gobject-introspection
  ];
  buildInputs = [
    gtk4
    libadwaita
  ];

  postInstall = ''
    cp $src/usr/share $out/share -r
  '';
}
```

### 0.6 — Regras de organização de código

| Camada | Diretório | Pode importar | NÃO pode importar |
|--------|-----------|---------------|--------------------|
| **UI — Pages** | `ui/` | `services/`, `utils/`, `ui/widgets/` | — |
| **UI — Widgets** | `ui/widgets/` | `utils/` | `services/`, `ui/` (sem deps circulares) |
| **Services** | `services/` | `utils/` | `ui/` (nunca importar UI) |
| **Utils** | `utils/` | stdlib apenas | `ui/`, `services/` |
| **Daemon Rust** | `big-parental-daemon/` | — | Python (processos separados) |

**Comunicação daemon ↔ UI:** Exclusivamente via D-Bus (nunca importação direta).

### 0.7 — Limites de tamanho por arquivo

| Tipo | Máximo sugerido | Ação se exceder |
|------|-----------------|-----------------|
| Widget / Block | ~200 linhas | Extrair subwidget |
| Page | ~300 linhas | Extrair bloco para `widgets/` |
| Service | ~250 linhas | Dividir por responsabilidade |
| Módulo Rust | ~300 linhas | Extrair submódulo |

### 0.8 — Passos de migração

1. Criar `pyproject.toml`, `flake.nix`, `default.nix`
2. Criar diretório `src/big_parental_controls/` com `__init__.py` e `__main__.py`
3. Mover serviços de `usr/share/.../services/` → `src/.../services/` (sem alteração de código)
4. Mover utils de `usr/share/.../utils/` → `src/.../utils/`
5. Adaptar imports (de relativos para pacote: `from big_parental_controls.services import ...`)
6. Mover `app.py`, `window.py` para `src/big_parental_controls/`
7. Mover/refatorar pages na Fase 4 (novo layout UI)
8. Atualizar `usr/bin/big-parental-controls` launcher para chamar o pacote
9. Atualizar PKGBUILD para build com `pyproject.toml`
10. Renomear `big-age-signal/` → `big-parental-daemon/`

**Nota:** O launcher `usr/bin/big-parental-controls` pode continuar como script
bash que chama `python -m big_parental_controls` para manter compatibilidade
com instalação manual via PKGBUILD.

---

## Fase 1: Coleta de Dados de Sessão (Prioridade: ALTA)

### 1.1 — `services/activity_service.py`

Serviço que agrega dados de uso de múltiplas fontes.

**Métodos principais:**

```python
class ActivityService:
    """Collect and aggregate usage data for supervised users."""

    def get_session_history(self, username: str, days: int = 7) -> list[SessionEntry]:
        """Return login sessions from wtmp/last.

        Returns list of SessionEntry(start: datetime, end: datetime|None,
                                     duration_minutes: int, tty: str)
        """

    def get_daily_usage(self, username: str, days: int = 30) -> dict[str, int]:
        """Return daily usage in minutes: {"2026-03-17": 145, ...}."""

    def get_hourly_distribution(self, username: str, days: int = 7) -> list[int]:
        """Return 24-element list with minutes used per hour slot."""

    def get_active_processes(self, uid: int) -> list[ProcessInfo]:
        """Return currently running processes for the user."""

    def get_app_usage(self, username: str, days: int = 7) -> list[AppUsageEntry]:
        """Return app usage history from /proc polling data."""
```

**Implementação da coleta via `last`:**

```python
def _parse_last_output(self, username: str, days: int) -> list[SessionEntry]:
    """Parse 'last' command output for session history."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    result = subprocess.run(
        ["last", "-n", "10000", username, "--time-format", "iso", "--since", since],
        capture_output=True, text=True, timeout=10
    )
    sessions = []
    for line in result.stdout.splitlines():
        # Parse ISO format: "rafael   tty2  2026-03-17T00:52:57-03:00 - 2026-03-17T01:16:23-03:00  (00:23)"
        # ...parsing logic...
        sessions.append(SessionEntry(start=start_dt, end=end_dt, ...))
    return sessions
```

**Implementação da coleta via `journalctl`:**

A coleta de dados do journal requer privilégios. O `activity_service.py` **não chama
journalctl diretamente** — usa o `group-helper` via pkexec para obter os dados:

```python
def _parse_logind_sessions(self, uid: int, days: int) -> list[SessionEntry]:
    """Get session data via group-helper (privileged)."""
    result = subprocess.run(
        ["pkexec", "/usr/lib/big-parental-controls/group-helper",
         "activity-sessions", str(uid), str(days)],
        capture_output=True, text=True, timeout=30
    )
    # Parse output...
```

**Nota sobre separação de responsabilidades:**
- **Python `activity_service.py`**: agrega sessões (via `last` direto + `group-helper` para journal)
- **Daemon Rust**: escreve snapshots de processo em `/var/lib/.../activity/{user}/YYYY-MM-DD.json`
- **Python lê** os JSONs de processo via D-Bus (`GetAppUsage`, `GetDailyTotals`, etc.)
- **Regra:** Apenas o daemon Rust **escreve** em `/var/lib/.../activity/`. Python **lê** via D-Bus.

### 1.2 — Armazenamento protegido dos dados de sessão

Dados de sessão ficam em `/var/lib/big-parental-controls/activity/` (permissão `root:root 700`). O usuário supervisionado **não tem acesso** — apenas o daemon Rust e o `group-helper` (via pkexec) escrevem/leem nesse diretório.

**Segurança:** Nunca armazenar dados de monitoramento em `~/.cache/` ou `~/.local/` do usuário supervisionado — ele poderia simplesmente apagar.

```
/var/lib/big-parental-controls/activity/
  rafael/
    sessions-2026-03.json    # Sessões do mês (parsed de last/journalctl)
    2026-03-17.json          # Snapshots de processo (do daemon Rust)
  minibruno/
    sessions-2026-03.json
```

**Formato JSON:**

```json
{
  "sessions": [
    {
      "start": "2026-03-17T00:52:57-03:00",
      "end": "2026-03-17T01:16:23-03:00",
      "duration_minutes": 23,
      "tty": "tty2",
      "session_type": "wayland"
    }
  ],
  "daily_totals": {
    "2026-03-17": 145,
    "2026-03-16": 210
  }
}
```

### 1.3 — Coleta privilegiada via `group-helper`

Alguns dados exigem `sudo`. Adicionar novos comandos ao `group-helper`:

```bash
# Novo comando: activity-sessions USERNAME DAYS
# Retorna JSON com sessões do wtmp + journalctl
activity-sessions)
    validate_username "$2"
    days="${3:-7}"
    # Validar que days é numérico (1-365) para evitar injeção
    if ! [[ "$days" =~ ^[0-9]+$ ]] || [ "$days" -lt 1 ] || [ "$days" -gt 365 ]; then
        echo "Invalid days parameter" >&2; exit 1
    fi
    last -n 10000 "$2" --time-format iso 2>/dev/null
    ;;
```

---

## Fase 2: Gráficos Nativos com Cairo (Prioridade: ALTA)

### 2.1 — `widgets/usage_chart.py`

Widget GTK4 que desenha gráficos usando PyCairo. **Sem dependências extras** — pycairo já está instalado.

**Tipos de gráfico:**

#### a) Gráfico de barras — Uso diário (últimos 7/14/30 dias)

```
Uso diário (minutos)
│
240 ┤          ██
180 ┤    ██    ██    ██
120 ┤    ██    ██    ██    ██
 60 ┤ ██ ██ ██ ██ ██ ██ ██ ██
  0 ┼──┬──┬──┬──┬──┬──┬──┬──
    Seg Ter Qua Qui Sex Sáb Dom
```

**Implementação essencial:**

```python
class UsageBarChart(Gtk.DrawingArea):
    """Bar chart showing daily usage in minutes."""

    def __init__(self):
        super().__init__()
        self._data: list[tuple[str, int]] = []  # (label, minutes)
        self._max_minutes = 0
        self.set_draw_func(self._on_draw)
        self.set_content_height(200)
        self.set_content_width(400)

    def set_data(self, data: list[tuple[str, int]]):
        self._data = data
        self._max_minutes = max((v for _, v in data), default=0)
        self.queue_draw()

    def _on_draw(self, area, cr, width, height):
        """Draw bars using Cairo context."""
        if not self._data:
            return

        # Use Adwaita accent color from the theme
        style = self.get_style_context()

        n = len(self._data)
        margin = 40
        chart_w = width - margin * 2
        chart_h = height - margin * 2
        bar_w = chart_w / n * 0.7
        gap = chart_w / n * 0.3

        # Draw bars
        for i, (label, minutes) in enumerate(self._data):
            bar_h = (minutes / self._max_minutes) * chart_h if self._max_minutes > 0 else 0
            x = margin + i * (bar_w + gap)
            y = margin + chart_h - bar_h

            # Accent color (blue)
            cr.set_source_rgba(0.21, 0.52, 0.89, 0.85)
            cr.rectangle(x, y, bar_w, bar_h)
            cr.fill()

            # Label below bar (use Pango for proper text rendering)
            # ...
```

#### b) Timeline heatmap — Distribuição por hora do dia

```
Hora   0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23
Seg    ░  ░  ░  ░  ░  ░  ░  ░  █  █  █  █  ▓  ░  ▓  █  █  █  █  █  ▓  ▓  ░  ░
Ter    ░  ░  ░  ░  ░  ░  ░  ░  █  █  █  ▓  ░  ░  █  █  █  █  █  ▓  ░  ░  ░  ░
...
```

Cores por intensidade de uso:
- Sem uso: cinza claro (theme bg)
- Baixo (< 15 min): azul claro
- Médio (15-45 min): azul
- Alto (> 45 min): azul escuro

#### c) Lista de aplicativos — Top apps por tempo de uso

```
┌─────────────────────────────────────────────┐
│ 🌐 Firefox                    2h 45min  ███████████████ │
│ 🖥️ Konsole                   1h 20min  ████████        │
│ 📝 Kate                        45min   █████           │
│ 📁 Dolphin                     30min   ████            │
│ 🎮 Steam                       15min   ██              │
└─────────────────────────────────────────────┘
```

### 2.2 — Paleta de cores temática

Usar cores do tema Adwaita por meio do `GtkStyleContext`:

```python
def _get_accent_color(widget: Gtk.Widget) -> tuple[float, float, float]:
    """Get the current accent color from adwaita theme."""
    # GTK4: use named colors from CSS
    # @accent_bg_color, @accent_color
    color = Gdk.RGBA()
    style = widget.get_style_context()
    if style.lookup_color("accent_bg_color", color):
        return (color.red, color.green, color.blue)
    return (0.21, 0.52, 0.89)  # Fallback: Adwaita blue
```

### 2.3 — Acessibilidade dos gráficos

Cada gráfico **deve ter**:
- `set_accessible_role(Gtk.AccessibleRole.IMG)`
- Label acessível descrevendo o conteúdo: `"Gráfico mostrando 2 horas e 45 minutos de uso hoje"`
- Tooltip com valores ao passar o mouse
- Navegação por teclado entre barras (foco marca a barra com contorno)
- Texto alternativo atualizado quando dados mudam

---

## Fase 3: Monitoramento de Apps via Daemon Rust (Prioridade: MÉDIA)

### 3.1 — Expandir `big-age-signal` → `big-parental-daemon`

O daemon Rust existente (`big-age-signal`) já roda como serviço D-Bus com `tokio` e `zbus`. Em vez de criar um script Python separado, **expandir o daemon Rust** para também monitorar processos. Isso é muito mais eficiente:

- Rust escaneia `/proc` ~100x mais rápido que Python
- O daemon já está rodando — sem processo extra
- Integração D-Bus nativa — a UI GTK consulta via bus
- Timer via `tokio::time::interval` — sem systemd timer adicional

**Renomear:** `big-age-signal` → `big-parental-daemon` (daemon unificado: age signal + monitoramento)

### 3.2 — Nova interface D-Bus: `br.com.biglinux.ParentalMonitor1`

Adicionar uma segunda interface D-Bus ao mesmo daemon:

```rust
#[interface(name = "br.com.biglinux.ParentalMonitor1")]
impl ParentalMonitor {
    /// Enable monitoring for a supervised user.
    /// Called by the GTK app when admin toggles monitoring on.
    async fn enable_user(&self, username: String, uid: u32) -> bool;

    /// Disable monitoring for a supervised user.
    async fn disable_user(&self, username: String) -> bool;

    /// Get list of currently monitored usernames.
    fn get_monitored_users(&self) -> Vec<String>;

    /// Get app usage summary for a user (last N days).
    /// Returns JSON: [{"app": "firefox", "display_name": "Firefox",
    ///                  "icon": "firefox", "minutes": 165}, ...]
    fn get_app_usage(&self, username: &str, days: u32) -> String;

    /// Get daily usage totals for a user (last N days).
    /// Returns JSON: {"2026-03-17": 145, "2026-03-16": 210, ...}
    fn get_daily_totals(&self, username: &str, days: u32) -> String;

    /// Get hourly distribution for a user (last N days).
    /// Returns JSON: [0, 0, 0, 0, 0, 0, 0, 0, 45, 60, 55, 50, ...] (24 slots)
    fn get_hourly_distribution(&self, username: &str, days: u32) -> String;

    /// Get recent sessions for a user.
    /// Returns JSON array of session objects.
    fn get_recent_sessions(&self, username: &str, limit: u32) -> String;

    /// Signal emitted every minute with active process snapshot.
    #[zbus(signal)]
    async fn snapshot_taken(&self, username: &str, processes: Vec<String>) -> Result<()>;

    #[zbus(property)]
    fn version(&self) -> &str { "1.0" }
}
```

### 3.3 — Implementação do scanner em Rust

```rust
use std::fs;
use std::path::Path;
use std::collections::HashMap;

/// Processes to ignore (system daemons, not user-facing apps)
const IGNORED_PROCESSES: &[&str] = &[
    "systemd", "dbus-broker", "dbus-daemon", "pipewire",
    "pipewire-pulse", "wireplumber", "kwin_wayland",
    "ksmserver", "plasmashell", "kded6", "xdg-desktop-portal",
    "xdg-document-portal", "xdg-permission-store",
    "gvfsd", "gvfsd-fuse", "at-spi-bus-launcher",
    "at-spi2-registryd", "ssh-agent", "gpg-agent",
    "polkitd", "Xwayland", "fcitx5", "kglobalaccel6",
    "kactivitymanagerd", "baloo_file", "kscreen_backend_launcher",
];

struct ProcessSnapshot {
    timestamp: chrono::NaiveDateTime,
    processes: Vec<String>,
}

fn scan_user_processes(uid: u32) -> Vec<String> {
    let mut apps = Vec::new();
    let Ok(entries) = fs::read_dir("/proc") else { return apps };

    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if !name_str.chars().all(|c| c.is_ascii_digit()) {
            continue;
        }

        let pid_path = entry.path();
        // Check owner UID via /proc/{pid}/status
        let status_path = pid_path.join("status");
        let Ok(status) = fs::read_to_string(&status_path) else { continue };

        let mut proc_uid = u32::MAX;
        for line in status.lines() {
            if let Some(rest) = line.strip_prefix("Uid:\t") {
                if let Some(first) = rest.split_whitespace().next() {
                    proc_uid = first.parse().unwrap_or(u32::MAX);
                }
                break;
            }
        }
        if proc_uid != uid {
            continue;
        }

        // Read process name
        let comm_path = pid_path.join("comm");
        let Ok(comm) = fs::read_to_string(&comm_path) else { continue };
        let comm = comm.trim();

        if IGNORED_PROCESSES.contains(&comm) {
            continue;
        }

        if !apps.contains(&comm.to_string()) {
            apps.push(comm.to_string());
        }
    }
    apps
}
```

### 3.4 — Loop de monitoramento com tokio

```rust
use tokio::time::{interval, Duration};

async fn monitor_loop(state: Arc<Mutex<MonitorState>>) {
    let mut tick = interval(Duration::from_secs(60));

    loop {
        tick.tick().await;

        let monitored = {
            let state = state.lock().unwrap();
            state.monitored_users.clone() // Vec<(String, u32)> — (username, uid)
        };

        for (username, uid) in &monitored {
            let processes = scan_user_processes(*uid);
            if !processes.is_empty() {
                // Append to daily snapshot file
                append_snapshot(username, &processes);
            }
        }
    }
}
```

### 3.5 — Armazenamento dos snapshots

Diretório: `/var/lib/big-parental-controls/activity/{username}/`

```json
// Arquivo: /var/lib/big-parental-controls/activity/rafael/2026-03-17.json
{
  "date": "2026-03-17",
  "snapshots": [
    {"t": "14:30", "p": ["firefox", "konsole", "dolphin"]},
    {"t": "14:31", "p": ["firefox", "konsole"]},
    {"t": "14:32", "p": ["firefox", "kate"]}
  ]
}
```

**Formato compacto:** `"t"` (tempo) e `"p"` (processos) para minimizar I/O.
Cada snapshot onde um app aparece = 1 minuto de uso.

**Escrita atômica:** Sempre gravar em arquivo temporário e depois renomear
para garantir integridade mesmo em caso de crash ou falta de energia:

```rust
fn atomic_write(path: &Path, content: &[u8]) -> std::io::Result<()> {
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, content)?;
    fs::rename(&tmp, path)?;
    Ok(())
}
```

### 3.6 — Cargo.toml: novas dependências

```toml
[dependencies]
zbus = { version = "5.14", default-features = false, features = ["tokio"] }
tokio = { version = "1.50", features = ["rt", "macros", "time", "sync"] }
nix = { version = "0.31", default-features = false, features = ["user"] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
chrono = { version = "0.4", default-features = false, features = ["clock"] }
```

**Justificativa:**
- `serde` + `serde_json`: serialização dos snapshots (já são dependências transitivas do zbus)
- `chrono`: timestamps dos snapshots (leve, sem TZ database)
- `tokio/time`: interval timer
- `tokio/sync`: `Mutex` para estado compartilhado entre D-Bus handler e monitor loop

### 3.7 — Serviço systemd: mudar de user para system

O daemon atual roda como **user service**. Para monitorar outros usuários, precisa rodar como **system service** com acesso a `/proc` de todos os UIDs:

```ini
# /usr/lib/systemd/system/big-parental-daemon.service
[Unit]
Description=BigLinux Parental Controls Daemon
After=dbus.service

[Service]
Type=dbus
BusName=br.com.biglinux.ParentalDaemon
ExecStart=/usr/lib/big-parental-controls/big-parental-daemon
User=root
# Hardening
ProtectHome=read-only
ProtectSystem=strict
ReadWritePaths=/var/lib/big-parental-controls
PrivateTmp=true
NoNewPrivileges=false
CapabilityBoundingSet=CAP_DAC_READ_SEARCH

[Install]
WantedBy=multi-user.target
```

### 3.7.1 — Política D-Bus: restringir acesso ao daemon

**CRÍTICO:** Sem política D-Bus, qualquer usuário (incluindo a criança supervisionada)
poderia chamar `DisableUser()` e parar o monitoramento.

```xml
<!-- /usr/share/dbus-1/system.d/br.com.biglinux.ParentalDaemon.conf -->
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <!-- Only root can own the bus name -->
  <policy user="root">
    <allow own="br.com.biglinux.ParentalDaemon"/>
  </policy>

  <!-- Only users in the 'wheel' group (admins) can call write methods -->
  <policy group="wheel">
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="br.com.biglinux.ParentalMonitor1"
           send_member="EnableUser"/>
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="br.com.biglinux.ParentalMonitor1"
           send_member="DisableUser"/>
  </policy>

  <!-- Any user can call read-only methods (needed for tray indicator) -->
  <policy context="default">
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="br.com.biglinux.ParentalMonitor1"
           send_member="GetMonitoredUsers"/>
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="br.com.biglinux.ParentalMonitor1"
           send_member="GetAppUsage"/>
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="br.com.biglinux.ParentalMonitor1"
           send_member="GetDailyTotals"/>
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="br.com.biglinux.ParentalMonitor1"
           send_member="GetHourlyDistribution"/>
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="br.com.biglinux.ParentalMonitor1"
           send_member="GetRecentSessions"/>
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="org.freedesktop.DBus.Properties"/>
    <allow send_destination="br.com.biglinux.ParentalDaemon"
           send_interface="org.freedesktop.DBus.Introspectable"/>
  </policy>
</busconfig>
```

**Nota sobre Polkit:** Para operações administrativas (Enable/Disable monitoring),
a política D-Bus acima restringe ao grupo `wheel`. Alternativamente, pode-se usar
Polkit actions com `pkexec` se necessário uma confirmação por senha, mas a restrição
por grupo D-Bus é suficiente pois já validamos que o app só é utilizável por admins.

### 3.7.2 — Daemon unificado (single binary)

O `big-age-signal` e o `big-parental-daemon` serão **unificados em um único binário
Rust** (`big-parental-daemon`) no **system bus**. Vantagens:

- **Um processo** — menos memória (~3-5MB em vez de ~6-10MB com dois)
- **Um runtime tokio** — sem duplicação de event loop
- **Uma conexão D-Bus** — reduz overhead de comunicação
- **Um pacote** — build, empacotamento e manutenção simplificados
- **Features opcionais** — monitoramento pode ser ativado/desativado sem afetar o age signal

**Interfaces D-Bus no system bus:**
- `br.com.biglinux.AgeSignal` — retorna age range do chamador (identifica UID via D-Bus peer credentials)
- `br.com.biglinux.ParentalMonitor1` — monitoramento de apps (métodos de escrita restritos ao wheel)

**Migração do AgeSignal para system bus:**
O daemon identifica o UID do processo chamador usando `zbus::Connection::peer_credentials()` ou
`zbus::message::Header::sender()` + D-Bus `GetConnectionUnixUser`. Assim, apps na sessão
do usuário supervisionado consultam `is_minor()` no system bus e recebem a resposta correta
para seu UID.

```rust
#[interface(name = "br.com.biglinux.AgeSignal")]
impl AgeSignal {
    /// Get age range of the calling process's user.
    async fn get_age_range(&self, #[zbus(header)] header: Header<'_>) -> String {
        let caller_uid = get_caller_uid(&self.connection, &header).await;
        if is_supervised(caller_uid) { "child".into() } else { "adult".into() }
    }
}
```

**Serviço systemd:** Apenas `big-parental-daemon.service` (system service).
O antigo `big-age-signal.service` (user service) é removido na migração.

### 3.8 — Seleção de usuários monitorados na UI

A interface GTK exibe uma lista de usuários supervisionados com toggle individual:

```python
# Na activity_page.py
class ActivityPage(Gtk.Box):
    def _build_monitoring_group(self):
        """Build the monitoring toggle group."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Monitored Users"))
        group.set_description(
            _("Choose which supervised accounts have activity tracking. "
              "The system checks running programs every minute.")
        )

        for user in supervised_users:
            row = Adw.SwitchRow()
            row.set_title(user.get_real_name() or user.get_user_name())
            row.set_subtitle(user.get_user_name())

            # Check if user is currently monitored via D-Bus
            is_monitored = self._daemon.get_monitored_users()
            row.set_active(user.get_user_name() in is_monitored)

            row.connect("notify::active", self._on_monitoring_toggled, user)
            group.add(row)

        return group

    def _on_monitoring_toggled(self, row, pspec, user):
        """Enable/disable monitoring for a user via D-Bus."""
        username = user.get_user_name()
        uid = user.get_uid()
        if row.get_active():
            # Call D-Bus: br.com.biglinux.ParentalMonitor1.EnableUser
            self._daemon.enable_user(username, uid)
        else:
            self._daemon.disable_user(username)
```

### 3.9 — Estado persistente dos usuários monitorados

Salvar em `/var/lib/big-parental-controls/monitored-users.json`:

```json
{
  "monitored": [
    {"username": "rafael", "uid": 1005},
    {"username": "minibruno", "uid": 1002}
  ]
}
```

O daemon Rust lê esse arquivo no startup para restaurar o estado.

### 3.10 — Mapeamento processo → app amigável

O daemon Rust faz o mapeamento uma vez no startup (cacheia):

```rust
/// Read all .desktop files and build comm→display_name map
fn build_desktop_map() -> HashMap<String, (String, String)> {
    // Returns: { "firefox" => ("Firefox", "firefox-icon"), ... }
    let mut map = HashMap::new();
    for dir in &["/usr/share/applications", "/usr/local/share/applications"] {
        for entry in fs::read_dir(dir).into_iter().flatten().flatten() {
            // Parse .desktop: Exec= line → extract binary name
            // Name= line → display name
            // Icon= line → icon name
        }
    }
    map
}
```

### 3.11 — Retenção e limpeza automática

O daemon limpa snapshots com mais de 30 dias ao iniciar:

```rust
fn cleanup_old_snapshots(base_dir: &Path, retention_days: u32) {
    let cutoff = chrono::Local::now().date_naive()
        - chrono::Duration::days(retention_days as i64);
    // Remove files older than cutoff
}
```

### 3.12 — Privacidade por design

- **Dados locais apenas** — snapshots em `/var/lib/` com permissão root
- **Retenção limitada** — 30 dias, limpeza automática
- **Agregado** — armazena apenas nomes de processos, sem argumentos de CLI
- **Opt-in por usuário** — admin escolhe quais usuários monitorar
- **Cleanup ao remover supervisão** — `group-helper remove-full` apaga `activity/{username}/`
- **Criança informada** — indicador de tray mostra "atividade monitorada"

---

## Fase 4: Redesign da UI — Navegação Centrada no Usuário (Prioridade: ALTA)

### 4.1 — Refatoração da `window.py`

Substituir `AdwNavigationSplitView` (sidebar) por `AdwNavigationView` (push/pop):

```python
class MainWindow(Adw.ApplicationWindow):
    """Main window with push/pop navigation — no sidebar."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(_("Parental Controls"))
        self.set_default_size(750, 680)

        self._accounts = AccountsServiceWrapper()
        self._nav_view = Adw.NavigationView()

        # Main page (always at bottom of stack)
        self._main_view = MainView(window=self)
        main_page = Adw.NavigationPage(
            title=_("Parental Controls"),
            child=self._main_view,
        )
        self._nav_view.add(main_page)
        self.set_content(self._nav_view)

    def show_user_detail(self, user):
        """Push user detail page onto the navigation stack."""
        detail = UserDetailPage(user=user, window=self)
        page = Adw.NavigationPage(
            title=user.get_real_name() or user.get_user_name(),
            child=detail,
        )
        self._nav_view.push(page)

    def refresh_main_view(self):
        """Refresh user list after create/remove."""
        self._main_view.refresh_users()
```

**Eliminados:** `window.ui`, `_SECTION_IDS`, `_USER_SECTIONS`, dropdown de usuário no headerbar, `GtkStack` de páginas.

### 4.2 — `pages/main_view.py` (Tela Principal)

```python
class MainView(Gtk.Box):
    """Landing screen: app intro + supervised users list."""

    def __init__(self, window):
        # AdwToolbarView
        #   ├── HeaderBar (title_widget=None, end=MenuButton)
        #   └── ScrolledWindow → Clamp(600) → VBox
        #         ├── AppIcon + Title + short description
        #         ├── "More info" Button → AdwAlertDialog
        #         │
        #         ├── UsersGroup (AdwPreferencesGroup)
        #         │     ├── UserRow: rafael  ● Online · 1h hoje  [→]
        #         │     ├── UserRow: minibruno  ○ Offline        [→]
        #         │     └── ...
        #         │
        #         ├── AddUserButton ("suggested-action")
        #         │
        #         ├── HelpGroup (AdwPreferencesGroup)
        #         │     ├── CVV 188 row
        #         │     ├── SaferNet row
        #         │     └── Disque 100 / CERT.br rows
        #         │
        #         └── ComplianceGroup (AdwPreferencesGroup)
        #               └── ECA Digital + UK Code + EU DSA
```

Cada `UserRow` é um `AdwActionRow` ativável:

```python
def _create_user_row(self, user):
    row = Adw.ActionRow()
    row.set_title(user.get_real_name() or user.get_user_name())

    # Status badge (online/offline + tempo hoje)
    is_online = self._check_user_online(user.get_user_name())
    today_min = self._activity_svc.get_today_minutes(user.get_user_name())

    if is_online:
        status = _("● Online · %s today") % self._format_duration(today_min)
    else:
        last_seen = self._activity_svc.get_last_session(user.get_user_name())
        status = _("○ Offline · Last: %s") % (last_seen or _("never"))

    row.set_subtitle(status)
    row.set_activatable(True)
    row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
    row.connect("activated", lambda r: self._window.show_user_detail(user))
    return row
```

### 4.3 — `pages/user_detail_page.py` (Tela do Usuário)

Página scrollável com todas as configurações e atividade de um usuário:

```python
class UserDetailPage(Gtk.Box):
    """All settings and activity graphs for a single supervised user."""

    def __init__(self, user, window):
        # AdwToolbarView
        #   ├── HeaderBar (back button automatic via NavigationView)
        #   └── ScrolledWindow → Clamp(700) → VBox
        #         ├── SummaryBlock (status, perfil etário)
        #         ├── TimeLimitsBlock (horários + limite diário)
        #         ├── ActivityBlock (gráficos + sessões)
        #         ├── AppFilterBlock (apps permitidos)
        #         ├── DnsBlock (filtro web)
        #         ├── MonitoringBlock (toggle + dados)
        #         ├── ActionsGroup (remover/excluir)
        #         └── ComplianceBanner (footer legal)
```

### 4.4 — Widgets reutilizáveis (blocos extraídos)

De cada `*_page.py` existente, extrair a lógica de UI para um widget embedável:

| Bloco | Origem | Diferença |
|-------|--------|-----------|
| `TimeLimitsBlock` | `time_limits_page.py` | Sem ScrolledWindow, `set_user()` |
| `AppFilterBlock` | `app_filter_page.py` | Sem ScrolledWindow, `set_user()` |
| `DnsBlock` | `dns_page.py` | Sem ScrolledWindow, `set_user()` |
| `SummaryBlock` | Novo | Status online, tempo hoje, perfil etário |
| `ActivityBlock` | Novo | Gráficos Cairo + sessões recentes |
| `MonitoringBlock` | Novo | Toggle monitoramento + info retenção |

Princípio: **cada bloco** é um `Gtk.Box` com `AdwPreferencesGroup(s)` que pode ser incluído em qualquer container. Serviços (`time_service`, `acl_service`, etc.) continuam inalterados.

### 4.4.1 — Empty states e confirmações

**Cada bloco** que depende de dados deve exibir um `AdwStatusPage` compacto quando
não há dados disponíveis:

- **ActivityBlock sem dados**: "Nenhum dado de atividade ainda. Ative o monitoramento
  abaixo para começar a registrar o uso."
- **ActivityBlock com monitoramento ativo, mas sem histórico**: "O monitoramento foi
  ativado. Os dados aparecerão após o primeiro uso."
- **Daemon não respondendo**: "O serviço de monitoramento não está disponível.
  Verifique se o serviço big-parental-daemon está ativo."

**Ações destrutivas** (excluir dados, remover supervisão, excluir conta) devem sempre
usar `AdwAlertDialog` com `Adw.ResponseAppearance.DESTRUCTIVE` e texto claro sobre
as consequências.

### 4.5 — Migração incremental

Para não quebrar tudo de uma vez:

1. **Criar `main_view.py` e `user_detail_page.py`** com imports dos blocos
2. **Extrair blocos** de cada `*_page.py` existente (copiar lógica de UI)
3. **Trocar `window.py`** para usar `AdwNavigationView` em vez de `AdwNavigationSplitView`
4. **Remover** `window.ui`, páginas antigas, dropdown de usuário
5. **Testar** cada bloco individualmente

---

## Fase 5: Conformidade Legal (Prioridade: ALTA)

### 5.1 — Leis de referência

#### Brasil — ECA Digital (Lei 15.211/2025)

| Artigo | Requisito | Status |
|--------|-----------|--------|
| Art. 12 | Verificação de idade proporcional; faixa etária, não idade exata | ✅ Implementado (Age Signal D-Bus retorna "child"/"adult") |
| Art. 13 | Minimização de dados; coleta apenas o necessário | ✅ Implementado (local-first, sem telemetria) |
| Art. 14 | Configurações padrão de alta privacidade | ✅ Implementado (defaults restritivos) |
| Art. 15 | Linguagem acessível, adequada à faixa etária | ⚠️ Parcial — precisa revisão UX |
| Art. 16 | Informações claras sobre tratamento de dados | ✅ Implementado (welcome_page + about) |
| Art. 17, IX | Canal de denúncia acessível | ✅ Implementado (support_page: Disque 100, SaferNet) |
| Art. 17, XII | Ferramentas de controle parental | ✅ Core do projeto |
| **Art. 18** | **Relatórios de uso para responsáveis** | **❌ A implementar (Fase 1-4)** |
| Art. 19 | Avaliação de impacto | ⚠️ Documentar |

#### EU — Digital Services Act (DSA)

| Requisito | Status |
|-----------|--------|
| Age-appropriate design | ✅ OARS ratings via malcontent |
| Transparency | ✅ Local-only, código aberto |
| Parental controls | ✅ Core do projeto |
| Usage reporting | ❌ A implementar |

**Nota:** O DSA é complementar ao GDPR. O DSA foca em obrigações de plataformas
digitais, enquanto o GDPR foca em proteção de dados pessoais. Ambos se aplicam.

#### UK — Children's Code (Age Appropriate Design Code)

| Standard | Status |
|----------|--------|
| Standard 2 — Data minimisation | ✅ |
| Standard 5 — Detrimental use detection | ❌ A implementar (alertas de uso excessivo) |
| Standard 7 — Default settings | ✅ |
| Standard 11 — Nudge techniques | ⚠️ A implementar (lembretes gentis de pausa) |
| Standard 14 — Parental controls | ✅ |

#### Brasil — LGPD (Lei 13.709/2018 — Lei Geral de Proteção de Dados)

| Artigo | Requisito | Status |
|--------|-----------|--------|
| **Art. 14** | Tratamento de dados de crianças e adolescentes exige **consentimento específico e em destaque** de pelo menos um responsável | **❌ A implementar (diálogo de consentimento informado)** |
| Art. 14, §1 | Informações sobre tratamento de dados devem ser em **linguagem clara e acessível**, adequada à compreensão | ✅ Linguagem simples na UI + indicador |
| Art. 14, §2 | Controladores não devem condicionar participação em atividades à entrega de dados pessoais além dos estritamente necessários | ✅ Monitoramento é opt-in por usuário |
| Art. 14, §4 | Controladores devem **publicar os tipos de dados coletados** e forma de utilização | ⚠️ Parcial — implementar no diálogo de consentimento |
| Art. 6, I | Consentimento como base legal | ✅ Via diálogo de consentimento informado |
| Art. 6, III | Necessidade para proteção da vida (safety) | ✅ Segurança da criança |
| Art. 18, I | Direito de **acesso** do titular aos dados pessoais | **❌ A implementar (view no indicador de tray)** |
| Art. 18, V | Direito de **oposição** ao tratamento | ✅ Admin pode desativar a qualquer momento |
| Art. 18, VI | Direito à **eliminação** dos dados a qualquer momento | **❌ A implementar (botão de exclusão com confirmação)** |
| Art. 46 | Medidas de segurança adequadas | ✅ Dados em `/var/lib/` (root:root 700), sem transmissão |
| Art. 49 | Armazenamento pelo tempo necessário à finalidade | ✅ Retenção de 30 dias com limpeza automática |

#### EU — GDPR (Regulamento 2016/679 — General Data Protection Regulation)

**Nota:** O GDPR Art. 2.2(c) isenta processamento em atividades pessoais/domésticas
("household exemption"). Controle parental em computador familiar se enquadra.
Porém, como o software pode ser usado em escolas/instituições, mantemos conformidade.

| Artigo | Requisito | Status |
|--------|-----------|--------|
| Art. 5.1(b) | Limitação de finalidade — apenas segurança da criança | ✅ Local-only, sem telemetria |
| Art. 5.1(c) | Minimização de dados — apenas o necessário | ✅ Só nomes de processo, sem argumentos CLI |
| Art. 5.1(e) | Limitação de armazenamento — pelo tempo necessário | ✅ 30 dias, limpeza automática |
| Art. 5.1(f) | Integridade e confidencialidade | ✅ root:root 700, escrita atômica, sem rede |
| Art. 6.1(a) | Base legal: consentimento | ✅ Diálogo de consentimento informado |
| **Art. 8** | Consentimento para menores — exige responsável legal | ✅ Diálogo de consentimento do admin (pai/responsável) |
| Art. 12 | Informações transparentes e em linguagem clara | ✅ Linguagem simples na UI e indicador de tray |
| **Art. 13** | Informações obrigatórias na coleta de dados | **⚠️ Melhorar diálogo de consentimento (ver 5.2a)** |
| Art. 15 | Direito de acesso do titular | ✅ "Ver meus dados" no indicador de tray |
| Art. 17 | Direito ao apagamento | ✅ Botão "Excluir dados" com confirmação |
| **Art. 20** | Direito à portabilidade dos dados | **❌ A implementar (exportar JSON)** |
| Art. 25 | Proteção por design e por padrão | ✅ Seção "Privacidade por design" |
| Art. 32 | Segurança do processamento | ✅ Escrita atômica, D-Bus protegido, root-only |
| **Art. 35** | DPIA (avaliação de impacto) | **⚠️ Documentar (ver abaixo)** |
| Recital 38 | Proteção específica de menores | ✅ Linguagem adequada à idade no indicador |

### 5.2 — Implementações necessárias para conformidade

#### a) Consentimento informado para monitoramento (LGPD Art. 14 + GDPR Art. 8/13)

Ao ativar monitoramento pela primeira vez, exibir `AdwAlertDialog` de consentimento.
Deve cobrir todas as informações exigidas pelo GDPR Art. 13:

```python
def _show_consent_dialog(self, user):
    """Show informed consent dialog before enabling monitoring."""
    dialog = Adw.AlertDialog()
    dialog.set_heading(_("Enable Activity Monitoring"))
    dialog.set_body(
        _("By enabling monitoring for %(user)s, the following data will be "
          "collected and stored exclusively on this device:\n\n"
          "Data collected:\n"
          "• Names of applications used (checked every 60 seconds)\n"
          "• Duration of use per application\n"
          "• Login and logout times\n\n"
          "Data controller: You (the device administrator).\n"
          "Purpose: Child safety monitoring.\n"
          "Legal basis: Parental consent (LGPD Art. 14, GDPR Art. 8, "
          "ECA Digital Art. 18).\n"
          "Retention: 30 days, then automatically deleted.\n"
          "Access: Only you can view detailed reports.\n"
          "Storage: Local only — no data is transmitted.\n\n"
          "Rights: You can disable monitoring, export data, or delete "
          "all data at any time. The supervised user will be informed "
          "that monitoring is active via the system tray indicator."
         ) % {"user": user.get_real_name() or user.get_user_name()}
    )
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("consent", _("I Understand and Consent"))
    dialog.set_response_appearance("consent", Adw.ResponseAppearance.SUGGESTED)
    dialog.connect("response", self._on_consent_response, user)
    dialog.present(self.get_root())
```

#### b) Banner legal na página Activity

```python
compliance_banner = Adw.ActionRow()
compliance_banner.set_title(_("Activity Monitoring"))
compliance_banner.set_subtitle(
    _(
        "Usage data stays exclusively on this device. "
        "In accordance with ECA Digital (Law 15.211/2025, Art. 18), "
        "LGPD (Law 13.709/2018, Art. 14), "
        "UK Children's Code, and EU Digital Services Act, "
        "parents may review usage patterns to ensure child safety. "
        "No data is transmitted externally."
    )
)
```

#### c) Alerta de uso excessivo (UK Code Standard 5)

Quando o uso diário exceder o limite configurado em mais de 20%:

```python
if daily_minutes > (configured_limit * 1.2):
    # Mostrar alerta inline (não toast - decisão crítica)
    self._excess_banner.set_title(_("Extended usage detected"))
    self._excess_banner.set_subtitle(
        _("%(user)s used the computer for %(time)s today, "
          "exceeding the %(limit)s limit.") % {...}
    )
```

#### d) Nudge de pausa (UK Code Standard 11)

Na sessão ativa, notificar o usuário supervisionado gentilmente:

```
"Você está usando o computador há 1 hora. Que tal uma pausa? 🌿"
```

Implementar via notificação D-Bus (não intrusivo).

#### e) Direito à informação da criança (Art. 15, ECA Digital + LGPD Art. 14 §1)

O indicador de tray (`big-supervised-indicator`) deve informar à criança:
- "Suas atividades são monitoradas pelo responsável"
- "Seu tempo de uso é: X horas hoje"
- Em linguagem simples e adequada à idade

#### f) Direito de acesso aos dados (LGPD Art. 18, I)

A criança (via responsável) tem direito de visualizar quais dados são coletados.
O indicador de tray deve ter opção "Ver meus dados" que mostra:
- Lista de apps registrados
- Tempo de uso por dia
- Período de retenção

```python
# No menu do indicador, para o usuário supervisionado:
def _show_my_data(self):
    """Show collected data to the supervised user (read-only)."""
    dialog = Adw.AlertDialog()
    dialog.set_heading(_("Your Activity Data"))
    # Busca dados via D-Bus (read-only, métodos permitidos para todos)
    usage = self._daemon.get_app_usage(self._username, 7)
    body = _("Apps used this week:\n")
    for app in usage:
        body += f"  • {app['display_name']}: {app['minutes']} min\n"
    body += _("\nData is kept for 30 days and then deleted.\n"
              "Only your parent/guardian can see detailed reports.")
    dialog.set_body(body)
    dialog.add_response("ok", _("OK"))
    dialog.present(self.get_root())
```

#### g) Direito à eliminação (LGPD Art. 18, VI)

O botão "Excluir dados" na seção MonitoringBlock do UserDetailPage deve:
1. Exibir `AdwAlertDialog` de confirmação com texto claro
2. Ao confirmar, deletar todos os arquivos em `/var/lib/big-parental-controls/activity/{username}/`
3. Chamar D-Bus para reiniciar os contadores internos do daemon

```python
def _on_delete_data_clicked(self, button):
    dialog = Adw.AlertDialog()
    dialog.set_heading(_("Delete Activity Data"))
    dialog.set_body(
        _("All activity data for %(user)s will be permanently deleted.\n"
          "This includes app usage history and session records.\n\n"
          "This action cannot be undone.") % {"user": self._username}
    )
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("delete", _("Delete All Data"))
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.connect("response", self._on_delete_response)
    dialog.present(self.get_root())
```

#### h) Portabilidade dos dados (GDPR Art. 20)

Botão "Exportar dados" no MonitoringBlock do UserDetailPage.
Exporta todos os dados de atividade do usuário em formato JSON legível:

```python
def _on_export_data_clicked(self, button):
    """Export user activity data to a JSON file."""
    # Use xdg-desktop-portal file chooser (Wayland-safe)
    dialog = Gtk.FileDialog()
    dialog.set_title(_("Export Activity Data"))
    dialog.set_initial_name(f"{self._username}_activity.json")
    dialog.save(self.get_root(), None, self._on_export_save)

def _on_export_save(self, dialog, result):
    file = dialog.save_finish(result)
    if file:
        data = self._daemon.get_all_data(self._username)
        path = file.get_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
```

#### i) Documentação de avaliação de impacto (GDPR Art. 35)

Incluir no repositório um arquivo `DPIA.md` com avaliação simplificada:
- **Natureza:** Monitoramento de uso de computador por menores
- **Escopo:** Local apenas, sem transmissão ou compartilhamento
- **Contexto:** Controle parental em ambiente doméstico/educacional
- **Risco para direitos:** Baixo — dados não saem do dispositivo
- **Medidas mitigatórias:** Consentimento, minimização, retenção limitada, acesso
  restrito, informação ao menor, direitos de acesso/exclusão/exportação
- **Conclusão:** Risco residual baixo — processamento local com garantias adequadas

**Nota:** O GDPR Art. 2.2(c) potencialmente isenta uso doméstico, mas documentar
a avaliação demonstra boa-fé e cobre uso institucional.

### 5.3 — Textos legais para a interface

Adicionar na welcome_page:

```python
legal_group = Adw.PreferencesGroup()
legal_group.set_title(_("Legal Framework"))

eca_row = Adw.ActionRow()
eca_row.set_title(_("ECA Digital — Brazil"))
eca_row.set_subtitle(
    _("Law 15.211/2025 — Safety, Privacy, and Parental Control "
      "for Children in the Digital Environment. "
      "This app implements Art. 12 (age verification), "
      "Art. 13 (data minimization), Art. 17 (protective measures), "
      "and Art. 18 (activity monitoring for parents).")
)

uk_row = Adw.ActionRow()
uk_row.set_title(_("UK Children's Code"))
uk_row.set_subtitle(
    _("Age Appropriate Design Code — 15 standards for "
      "child-safe digital services, including data minimization, "
      "default protections, and parental controls.")
)

eu_row = Adw.ActionRow()
eu_row.set_title(_("EU Digital Services Act"))
eu_row.set_subtitle(
    _("Regulation 2022/2065 — Transparency, user safety, "
      "and minors' protection in digital platforms.")
)

lgpd_row = Adw.ActionRow()
lgpd_row.set_title(_("LGPD — Brazil"))
lgpd_row.set_subtitle(
    _("Law 13.709/2018 — General Data Protection Law. "
      "This app complies with Art. 14 (children's data requires "
      "specific parental consent), Art. 18 (right to access and "
      "delete data), and Art. 46 (security measures).")
)

gdpr_row = Adw.ActionRow()
gdpr_row.set_title(_("GDPR — European Union"))
gdpr_row.set_subtitle(
    _("Regulation 2016/679 — General Data Protection Regulation. "
      "Compliant with Art. 8 (child consent via parent), "
      "Art. 13 (transparent information), Art. 17 (right to erasure), "
      "Art. 20 (data portability), and Art. 25 (privacy by design).")
)
```

---

## Fase 6: Aprimoramentos no Indicador de Tray (Prioridade: MÉDIA)

### 6.1 — Informar monitoramento à criança

Atualizar `big-supervised-indicator` para exibir:

```python
# No menu do indicador, adicionar:
info_item = Gtk.MenuItem(label=_("Your computer time today: %s") % formatted_time)
monitoring_item = Gtk.MenuItem(label=_("Activity is shared with your parent"))
```

### 6.2 — Notificação de pausa gentil

Via `notify-send` ou D-Bus `org.freedesktop.Notifications`:

```python
def _send_break_reminder(self, username: str, minutes_used: int):
    subprocess.run([
        "notify-send",
        "--app-name=Big Parental Controls",
        "--icon=preferences-system-time-symbolic",
        _("Time for a break!"),
        _("You've been using the computer for %d minutes. "
          "A short break helps you feel better.") % minutes_used,
    ], timeout=5)
```

---

## Fase 7: Testes (Prioridade: ALTA)

### 7.1 — Novos testes unitários

```
tests/
  test_activity_service.py    # Parsing de last, journalctl
  test_daemon_client.py       # Cliente D-Bus para daemon Rust, agregação de apps
  test_usage_chart.py         # Renderização Cairo (snapshot)
  test_compliance.py          # Textos legais presentes na interface
```

### 7.2 — Casos de teste prioritários

```python
# test_activity_service.py
class TestActivityService:
    def test_parse_last_output_normal(self):
        """Parse normal 'last' output with iso timestamps."""

    def test_parse_last_output_still_logged_in(self):
        """Handle 'still logged in' sessions correctly."""

    def test_parse_last_output_crash(self):
        """Handle crash entries (no clean logout)."""

    def test_daily_usage_aggregation(self):
        """Aggregate minutes per day correctly."""

    def test_hourly_distribution(self):
        """Build 24-hour slots from session data."""

    def test_empty_history(self):
        """Return empty lists when no history exists."""

    def test_corrupted_cache(self):
        """Handle corrupted JSON cache gracefully."""

# test_daemon_client.py
class TestDaemonClient:
    def test_get_app_usage_from_dbus(self):
        """Query daemon for app usage via D-Bus."""

    def test_filter_system_processes(self):
        """Verify system daemons are excluded from results."""

    def test_aggregate_snapshots_by_app(self):
        """Count minutes per app from daemon response."""

    def test_enable_disable_monitoring(self):
        """Toggle monitoring per user via D-Bus."""

    def test_daemon_not_running(self):
        """Handle daemon not running gracefully."""

# test_compliance.py
class TestCompliance:
    def test_eca_reference_in_welcome(self):
        """ECA Digital law reference exists in welcome page."""

    def test_privacy_statement_present(self):
        """Privacy statement exists in welcome page."""

    def test_support_channels_present(self):
        """Support channels (Disque 100, SaferNet) are present."""

    def test_no_external_data_transmission(self):
        """Verify no HTTP/network calls exist in services."""
```

---

## Fase 8: Empacotamento e Tradução (Prioridade: MÉDIA)

### 8.1 — PKGBUILD: atualizar para pyproject.toml

```bash
# No PKGBUILD, trocar a instalação manual por build padrão Python:
build() {
    cd "$srcdir/$pkgname"
    python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/$pkgname"
    python -m installer --destdir="$pkgdir" dist/*.whl
    # Copiar arquivos de sistema (systemd, dbus, polkit, icons)
    install -Dm644 usr/lib/systemd/system/big-parental-daemon.service \
        "$pkgdir/usr/lib/systemd/system/big-parental-daemon.service"
    install -Dm644 usr/share/dbus-1/system.d/br.com.biglinux.ParentalDaemon.conf \
        "$pkgdir/usr/share/dbus-1/system.d/br.com.biglinux.ParentalDaemon.conf"
    # ... demais arquivos de sistema
}
```

### 8.2 — Build do daemon Rust

```bash
# No PKGBUILD, adicionar build do daemon:
build() {
    # Python
    cd "$srcdir/$pkgname"
    python -m build --wheel --no-isolation
    # Rust
    cd "$srcdir/$pkgname/big-parental-daemon"
    cargo build --release
}

package() {
    # ...
    install -Dm755 big-parental-daemon/target/release/big-parental-daemon \
        "$pkgdir/usr/lib/big-parental-controls/big-parental-daemon"
}
```

### 8.3 — Novas strings para tradução

Estimar ~40 novas strings traduzíveis para:
- Página Activity (títulos, labels, tooltips)
- Textos legais (ECA, UK Code, DSA)
- Notificações de pausa
- Informações no indicador de tray

Executar `update_translations.sh` após implementação e enviar `.pot` atualizado para tradutores.

---

## Cronograma Sugerido de Implementação

| Fase | Descrição | Complexidade | Dependências |
|------|-----------|--------------|--------------|
| **0** | Reestruturar projeto: `pyproject.toml`, `src/`, nix files | Média | Nenhuma |
| **1** | `activity_service.py` — coleta via `last` + `journalctl` | Média | Fase 0 |
| **2** | `widgets/usage_chart.py` — gráficos Cairo | Alta | Fase 1 |
| **3** | Daemon Rust: /proc scanner + D-Bus API unificado | Média | Fase 0 |
| **4** | Redesign UI: `main_view.py` + `user_detail_page.py` + blocos | Alta | Fases 1, 2, 3 |
| **5** | Textos legais + compliance (LGPD, GDPR, ECA) | Baixa | Fase 4 |
| **6** | Atualizar `big-supervised-indicator` | Baixa | Fase 1 |
| **7** | Testes | Média | Fases 1-6 |
| **8** | PKGBUILD + traduções + Nix packaging | Baixa | Fases 0-7 |

### Ordem de implementação recomendada

```
0. Reestruturar projeto (pyproject.toml + src/ + nix)
   ↓
1. activity_service.py (coleta de dados)
   ↓
2. usage_chart.py (widgets Cairo)  ←  pode ser paralelo com 3
   ↓
3. Daemon Rust (scanner /proc)     ←  pode ser paralelo com 2
   ↓
4. Redesign UI (MainView + UserDetailPage + blocos)
   ↓
5. Compliance (textos legais) + Indicator (tray updates)
   ↓
6. Testes + Empacotamento + Traduções
```

---

## Versões de Dependências e Componentes (verificado em 2025-07)

### Ambiente do sistema (BigLinux/Manjaro)

| Componente | Versão instalada | Notas |
|------------|------------------|-------|
| **libadwaita** | **1.8.4** | Última estável — acesso a todos widgets até 1.8 |
| **GTK4** | **4.20.3** | Última estável |
| **python-gobject** | 3.54.5 | PyGObject — bindings Python para GLib/GTK/Adw |
| **pycairo** | 1.29.0 | Pacote `python-cairo` no Arch |
| **Rust** | 1.93.1 | Toolchain completa |
| **Cargo** | 1.93.1 | — |
| **systemd** | 259 | Suporte completo a D-Bus activation + timers |

### Dependências Rust (Cargo.toml)

| Crate | Versão mínima | Última disponível | Motivo |
|-------|---------------|-------------------|--------|
| **zbus** | 5.14 | 5.14.0 | D-Bus async com tokio — API v5 estável |
| **tokio** | 1.50 | 1.50.0 | Runtime async — features: rt, macros, time, sync |
| **nix** | 0.31 | 0.31.2 | Bindings POSIX para UID/GID lookup |
| **serde** | 1.0 | 1.0.228 | Serialização de snapshots JSON |
| **serde_json** | 1.0 | 1.0.149 | Formato JSON para /var/lib/ |
| **chrono** | 0.4 | 0.4.44 | Timestamps — features: clock (sem tz database) |

### Dependências Python (pyproject.toml)

| Pacote | Versão mínima | Notas |
|--------|---------------|-------|
| **PyGObject** | ≥3.50.0 | Bindings GObject para Adw/GTK4 |
| **pycairo** | ≥1.25.0 | Gráficos nativos via `Gtk.DrawingArea` |

> **Nota:** PyGObject e pycairo são dependências de sistema (`python-gobject`, `python-cairo`).
> Não instalar via pip — devem vir do repositório da distro para compatibilidade com typelibs.

### Widgets libadwaita — Guia de Uso (1.8.4)

#### Widgets que DEVEMOS usar (modernos, não-deprecated)

| Widget | Desde | Uso no projeto |
|--------|-------|----------------|
| `Adw.ApplicationWindow` | 1.0 | Janela principal (com suporte a breakpoints) |
| `Adw.NavigationView` | 1.4 | Container principal — push/pop de páginas |
| `Adw.NavigationPage` | 1.4 | Cada tela (main_view, user_detail) |
| `Adw.ToolbarView` | 1.4 | Wrapper para HeaderBar + content + bottom bar |
| `Adw.HeaderBar` | 1.0 | Barra de título com botão voltar automático |
| `Adw.Breakpoint` | 1.4 | Layout adaptativo (mobile/desktop) |
| `Adw.PreferencesGroup` | 1.0 | Blocos de configuração (time, dns, apps) |
| `Adw.PreferencesPage` | 1.0 | Container scrollável para PreferencesGroups |
| `Adw.ActionRow` | 1.0 | Linha com título + subtítulo + suffix widget |
| `Adw.SwitchRow` | 1.4 | Toggle on/off (monitoramento, filtros) |
| `Adw.ExpanderRow` | 1.0 | Seção expansível (detalhes de app) |
| `Adw.SpinRow` | 1.4 | Input numérico (limites de tempo em horas) |
| `Adw.StatusPage` | 1.0 | Empty states (sem dados, daemon offline) |
| `Adw.AlertDialog` | **1.5** | Confirmações e diálogos críticos |
| `Adw.AboutDialog` | **1.6** | Tela "Sobre" do aplicativo |
| `Adw.ButtonRow` | **1.6** | Linha que age como botão (exportar dados, ver todos) |
| `Adw.Spinner` | **1.6** | Loading indicator inline (enquanto carrega dados) |
| `Adw.Banner` | 1.3 | Aviso persistente no topo (daemon offline, alerta legal) |
| `Adw.Clamp` | 1.0 | Limitar largura máxima do conteúdo |

#### Widgets NOVOS que devemos considerar

| Widget | Desde | Possível uso |
|--------|-------|-------------|
| `Adw.WrapBox` | **1.7** | Tags de categorias de apps, badges de status |
| `Adw.BottomSheet` | 1.5 | Detalhes rápidos em tela pequena (alternativa futura) |

#### Widgets DEPRECATED — NÃO usar

| Widget deprecated | Desde | Substituto correto |
|-------------------|-------|-------------------|
| `Adw.MessageDialog` | 1.6 | → `Adw.AlertDialog` (desde 1.5) |
| `Adw.AboutWindow` | 1.6 | → `Adw.AboutDialog` (desde 1.6) |
| `Adw.Leaflet` | 1.4 | → `Adw.NavigationView` ou `Adw.NavigationSplitView` |
| `Adw.ViewSwitcherTitle` | 1.4 | → `Adw.ViewSwitcher` + `Adw.Breakpoint` |
| `Adw.Flap` | 1.4 | → `Adw.NavigationSplitView` ou `Adw.BottomSheet` |

#### Padrão XML recomendado para cada página

```xml
<!-- Cada página segue este padrão: NavigationPage → ToolbarView → HeaderBar + content -->
<object class="AdwNavigationPage">
  <property name="title" translatable="yes">Detalhes do Usuário</property>
  <property name="tag">user-detail</property>
  <property name="child">
    <object class="AdwToolbarView">
      <child type="top">
        <object class="AdwHeaderBar"/>
      </child>
      <property name="content">
        <object class="AdwPreferencesPage">
          <!-- PreferencesGroups aqui -->
        </object>
      </property>
    </object>
  </property>
</object>
```

#### Loading states com Adw.Spinner (1.6+)

```python
# Enquanto dados carregam do daemon D-Bus
spinner = Adw.Spinner()
status = Adw.StatusPage(
    title=_("Carregando dados de atividade..."),
    paintable=Adw.SpinnerPaintable.new(spinner),
)
# Substituir por conteúdo real quando dados chegarem
```

#### Adw.ButtonRow para ações em listas

```python
# Em vez de botão solto, usar ButtonRow dentro de PreferencesGroup
export_row = Adw.ButtonRow(
    title=_("Exportar dados de atividade"),
    start_icon_name="document-save-symbolic",
)
export_row.connect("activated", self._on_export_clicked)
actions_group.add(export_row)
```

---

## Decisões de Design

### Por que Cairo nativo e não matplotlib?

1. **Zero dependências extras** — pycairo já é dependência transitiva do GTK4
2. **Integração perfeita** com o tema Adwaita (cores, fontes, DPI)
3. **Performance** — rendering direto na GPU via GSK
4. **Tamanho do pacote** — matplotlib traz numpy + ~150MB de deps
5. **Consistência visual** — mesma engine de rendering do resto da UI

### Por que /proc polling no daemon Rust?

1. **Zero dependências** — /proc é sempre disponível no Linux
2. **Leveza** — Rust escaneia /proc em <1ms, polling a cada 60s é imperceptível
3. **Reutilização** — daemon já roda com tokio/zbus, basta expandir
4. **Privacidade** — captura apenas nomes de processos visíveis, sem argumentos de CLI
5. **Integração D-Bus** — UI consulta dados via bus, sem parsing de arquivos
6. **Opt-in por usuário** — admin escolhe quais usuários monitorar na interface
7. **Desvantagem aceitável** — apps que rodam <1min não são capturados (irrelevante para controle parental)

### Por que /var/lib/ e não ~/.cache/ ou banco de dados?

1. **Segurança** — a criança supervisionada não pode apagar dados em `/var/lib/` (root-only)
2. **Simplicidade** — JSON files são legíveis e debuggáveis
3. **Coerência** — o projeto já usa `/var/lib/big-parental-controls/` para config (time-limits)
4. **Escala adequada** — com 4 usuários e 30 dias, são ~120 arquivos JSON pequenos
5. **Limpeza automática** — daemon Rust apaga snapshots >30 dias no startup

---

## Riscos e Mitigações

| Risco | Impacto | Mitigação |
|-------|---------|----------|
| `last` não disponível | Sem dados de sessão | Fallback para journalctl _UID via group-helper |
| Logs antigos removidos (journalctl vacuum) | Dados perdidos | `/var/lib/` preserva histórico processado (independente do journal) |
| Muitas execuções curtas (<1min) | Apps não capturados | Aceitável para controle parental — foco em uso prolongado |
| Criança tenta apagar dados de monitoramento | Falha de segurança | Dados em `/var/lib/` (root:root 700) — sem acesso do supervisionado |
| Criança desativa monitoramento via D-Bus | Falha de segurança | Política D-Bus restringe EnableUser/DisableUser ao grupo wheel |
| Crash do daemon durante escrita | JSON corrompido | Escrita atômica (write tmp + rename) |
| Daemon não rodando quando UI consulta | UI sem dados | Empty state informativo + verificação do serviço |
| UTF-8 em nomes de usuário | Parsing quebra | Validação já existente em `users_page.py` |
| Fuso horário | Horários errados | Usar datetime com tzinfo, nunca naive |

## Validação na VM

Após cada fase, testar na VM (192.168.1.31):

```bash
# Conectar
sshpass -p big ssh -o StrictHostKeyChecking=no bruno@192.168.1.31

# Copiar arquivos alterados
sshpass -p big scp -r big-parental-controls/usr/share/biglinux/parental-controls/ \
  bruno@192.168.1.31:/usr/share/biglinux/parental-controls/

# Testar como rafael (logar no SDDM, gerar atividade, e conferir na conta bruno)

# Executar testes
pytest tests/ -v
```

---

## Notas Adicionais

### Privacidade por design

- **Nenhum dado sai da máquina** — princípio fundamental
- **Dados protegidos em `/var/lib/`** — root-only, criança não pode apagar/modificar
- **Sem auditd** — removido do escopo, /proc polling é mais leve e suficiente
- **Criança é informada** — indicador de tray mostra status de monitoramento
- **Criança pode ver seus dados** — opção "Ver meus dados" no tray (LGPD Art. 18, I)
- **Dados agregados** — gráficos mostram totais, não detalhes granulares
- **Retenção limitada** — 30 dias, limpeza automática pelo daemon
- **Direito ao esquecimento** — ao remover supervisão, dados são apagados
- **Exclusão a qualquer momento** — admin pode deletar dados via UI (LGPD Art. 18, VI)
- **Portabilidade** — exportação em JSON legível (GDPR Art. 20)
- **Consentimento informado** — diálogo explícito ao ativar monitoramento (LGPD Art. 14, GDPR Art. 8/13)
- **D-Bus protegido** — métodos de escrita restritos ao grupo wheel (política D-Bus)

### Acessibilidade

- Todos os gráficos terão texto alternativo (screen reader)
- Dados numéricos disponíveis como texto (não apenas visual)
- Navegação por teclado nos gráficos
- Contraste adequado seguindo WCAG 2.1 AA
