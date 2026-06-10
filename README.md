# Rolls Solar Controller — Home Assistant Custom Integration

Integrare personalizată pentru Home Assistant care deschide automat jaluzelele
(storuri, rulouri, orice entitate `cover`) folosind surplusul de energie solară.
Când panourile fotovoltaice produc mai mult decât consumi, integrarea deschide
jaluzelele pe rând, în ordinea configurată, fără să consume energie din rețea.

## Cuprins

- [Cum e structurat codul](#structura-codului)
- [Cum funcționează](#cum-funcționează)
- [Entități create](#entități-create)
- [Dashboard (Lovelace)](#dashboard-lovelace)
- [Instalare](#instalare)
- [Configurare](#configurare)
- [Setări ajustabile](#setări-ajustabile)
- [Teste](#teste)
- [Release](#release)

---

## Structura codului

```
custom_components/rolls_ha/
├── __init__.py        — setup/teardown al config entry-ului, inițializează runtime store
├── config_flow.py     — wizard de configurare (3 pași) + options flow + reconfigure
├── const.py           — toate constantele: chei config, valori implicite, statusuri
├── coordinator.py     — logica de control (DataUpdateCoordinator), polling + reactiv
├── number.py          — entități Number (slider/input) pentru setări ajustabile live
├── sensor.py          — entități Sensor: surplus solar, status per jaluzea
├── switch.py          — entități Switch: control automat global + activ per jaluzea
├── manifest.json      — metadata HACS/HA (domain, version, iot_class)
└── translations/
    ├── en.json        — etichete UI în engleză
    └── ro.json        — etichete UI în română
```

### `__init__.py` — Entry point

La `async_setup_entry` se inițializează un runtime store în `hass.data[DOMAIN][entry_id]`
cu valorile din options (putere motor, timp stabilizare) și stările inițiale ale jaluzelelor
(toate `pending`). Coordinatorul este instanțiat, se face primul refresh, apoi se
înregistrează platformele (`switch`, `number`, `sensor`).

La `async_unload_entry` se anulează subscripțiile de stare și se eliberează datele din `hass.data`.

### `coordinator.py` — Creierul integrației

`RollsCoordinator` extinde `DataUpdateCoordinator` și rulează logica de control în două moduri:

1. **Polling** — la fiecare 30 de secunde
2. **Reactiv** — prin `async_track_state_change_event` pe senzorii solar și rețea;
   orice schimbare declanșează un refresh cu debounce de 3 secunde

Subscripții suplimentare:

- **Cover state changes** — detectează operarea manuală a oricărei jaluzele
- **Midnight reset** — `async_track_time_change` la 00:00:00 resetează toate stările

### `config_flow.py` — Wizard de configurare

Setup în 3 pași, plus options flow și reconfigure flow:

|                     | Step                                                              |
| ------------------- | ----------------------------------------------------------------- |
| **Step 1 – solar**  | Senzor producție solar, senzor rețea, convenție semn senzor rețea |
| **Step 2 – covers** | Lista de entități `cover` în ordinea de activare                  |
| **Step 3 – setări** | Putere motor (W), timp stabilizare (s)                            |

Options flow permite editarea setărilor din Step 3 fără a reinstala integrarea.
Reconfigure flow permite schimbarea senzorilor și listei de jaluzele.

### `sensor.py`, `switch.py`, `number.py` — Entități HA

Toate entitățile extind `CoordinatorEntity` și se actualizează automat când coordinatorul
publică date noi. Entitățile `switch` și `number` folosesc în plus `RestoreEntity` pentru
a-și recupera ultima valoare după un restart al HA.

---

## Cum funcționează

### Calculul surplusului

```
surplus = grid_export
        = grid_raw          (dacă convenție: pozitiv = export)
        = -grid_raw         (dacă convenție: pozitiv = import — Shelly EM standard)

surplus_virtual = surplus + motor_power × nr_jaluzele_în_mișcare
```

**De ce surplus virtual?** Când un motor de jaluzea rulează (consumă ~150 W),
valoarea exportată în rețea scade cu 150 W. Fără compensare, calculul ar părea că
surplusul a dispărut și ar opri coada. Adăugând înapoi puterea motorului activ,
sistemul vede surplusul real disponibil.

### Stările automatizării per jaluzea

```
PENDING       — așteptare surplus; jaluzea nu a fost atinsă azi
OPENING       — coordinator a trimis comanda, motorul rulează
AUTO_OPENED   — jaluzea a fost deschisă de integrare azi
MANUAL        — operare manuală detectată; ignorată tot restul zilei
```

O jaluzea cu `switch.activ_<jaluzea> = OFF` este sărită din coadă
(nu apare în stările de mai sus, afișează `Dezactivat`).

### Logica de decizie (per ciclu)

```
1. Calculează surplus_virtual
2. Dacă surplus_virtual < motor_power și un motor e în mișcare:
      → trimite stop_cover, jaluzea revine la PENDING
      → la revenirea surplusului jaluzea va fi redeschisă
3. Dacă vreun motor e în mișcare și surplus e OK — așteaptă finalizarea lui
4. Parcurge coada PENDING; jaluzele deja la poziția țintă sunt marcate
   AUTO_OPENED instant și se sare la urm. fără a aștepta ciclul următor
5. Dacă surplus_virtual ≥ motor_power:
      → trimite cover.open_cover (sau set_cover_position dacă poziție < 100%)
      → jaluzea devine OPENING; la finalizare → AUTO_OPENED
      → continuă evaluarea pentru jaluzea următoare
6. Dacă surplus_virtual < motor_power — rămâne PENDING, reîncearcă la ciclul următor
```

### Detectarea operării manuale

La fiecare serviciu apelat de coordinator se creează un `Context` propriu și se salvează
`context_id` + timestamp. La orice `state_changed` pe o jaluzea gestionată:

- Dacă `event.context.id` sau `event.context.parent_id` coincide cu `context_id` salvat → schimbare inițiată de coordinator → ignorată
- Dacă schimbarea are loc **în 5 minute** de la ultima acțiune a coordinatorului → perioadă de grație (motorul e încă în mișcare) → ignorată
- Orice altă schimbare → **MANUAL** → jaluzea ignorată pentru restul zilei

### Tabel de decizii

| Scenar | Surplus   | Stare jaluzea  | Activ | Rezultat                                     |
| ------ | --------- | -------------- | ----- | -------------------------------------------- |
| S1     | ≥ prag    | PENDING        | Da    | Deschidere imediată                          |
| S2     | < prag    | PENDING        | Da    | Rămâne PENDING                               |
| S3     | < prag    | OPENING        | Da    | stop_cover, revine la PENDING                |
| S4     | ≥ prag    | AUTO_OPENED    | Da    | Sărită (deja deschisă)                       |
| S5     | orice     | MANUAL         | Da    | Sărită (operare manuală)                     |
| S6     | orice     | orice          | Nu    | Sărită (dezactivată)                         |
| S7     | ≥ prag    | PENDING        | Da    | Alt motor în mișcare (OK surplus) — așteptare |
| S8     | orice     | PENDING        | Da    | Deja la poziția țintă → AUTO_OPENED instant  |

### Reset la miezul nopții

La `00:00:00` toate jaluzelele cu `cover_active = True` sunt resetate la `PENDING`.
Jaluzelele cu switch-ul dezactivat (`cover_active = False`) nu sunt atinse.
Timer-ul de stabilizare, mișcările în curs și acțiunile coordinator-ului sunt șterse.

---

## Entități create

### Sensori

| Entitate                  | Tip           | Valoare                                                                                                                     | Atribute                                                                                                                                              |
| ------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sensor.surplus_solar`    | Sensor (W)    | Export rețea curent                                                                                                         | `solar_power_w`, `grid_export_w`, `motor_power_w`, `jaluzele_deschise`, `jaluzele_deschise_lista`, `jaluzele_in_asteptare`, `action_log`, `cycle_log` |
| `sensor.status_<jaluzea>` | Sensor (text) | `Așteptare surplus` / `Deschidere automată` / `Deschis automat` / `Control manual` / `Dezactivat` / `Control automat oprit` | `pozitie` (%), `stare_cover`, `este_deschisa`, `stare_automatizare`, `cover_entity_id`                                                                |

Atributele `sensor.status_<jaluzea>` sunt citite **live** din entitatea cover sursă
(ex. Shelly Cover) la fiecare actualizare:

| Atribut              | Exemplu                    | Descriere                                                        |
| -------------------- | -------------------------- | ---------------------------------------------------------------- |
| `pozitie`            | `80`                       | Poziția curentă raportată de jaluzea (0–100%)                    |
| `stare_cover`        | `"open"`                   | Starea HA: `open` / `closed` / `opening` / `closing` / `stopped` |
| `este_deschisa`      | `true`                     | `true` dacă starea e `open`/`opening` sau poziție > 0            |
| `stare_automatizare` | `"auto_opened"`            | Starea internă: `pending` / `opening` / `auto_opened` / `manual` |
| `cover_entity_id`    | `"cover.dormitor_rasarit"` | Entity ID-ul sursei                                              |

### Switch-uri

| Entitate                       | Descriere                                                      |
| ------------------------------ | -------------------------------------------------------------- |
| `switch.control_automat_solar` | Activează/dezactivează controlul solar pentru toate jaluzelele |
| `switch.activ_<jaluzea>`       | Include/exclude o jaluzea individuală din coadă                |

### Number-uri (ajustabile live)

| Entitate                              | Domeniu   | Default | Descriere                                                   |
| ------------------------------------- | --------- | ------- | ----------------------------------------------------------- |
| `number.prag_putere_motor`            | 10–5000 W | 150 W   | Surplusul minim necesar pentru a porni un motor |
| `number.pozitie_deschidere_<jaluzea>` | 10–100 %  | 100 %   | La ce procent se deschide jaluzea respectivă    |

---

## Dashboard (Lovelace)

Integrarea **generează automat** un fișier de dashboard la:

```
<config>/www/rolls_ha_dashboard.yaml
```

Fișierul este regenerat la fiecare pornire a HA și la orice modificare de configurație.

### Import dashboard

**Settings → Dashboards → Add dashboard → From YAML** → selectează fișierul de mai sus.

### Structura dashboard-ului generat

| Secțiune      | Conținut                                                    |
| ------------- | ----------------------------------------------------------- |
| Header        | Producție · Rețea · Surplus (3 tile-uri)                    |
| Control       | Control automat switch · Deschise azi (2 tile-uri)          |
| Setări        | Prag motor (W) · Timp stabilizare (s)                       |
| Control rapid | Toate jaluzelele cu butoane ↑ ■ ↓                           |
| Per jaluzea   | Câte un `vertical-stack` pentru fiecare jaluzea configurată |
| Footer        | Log activitate recentă · Grafic surplus 2h                  |

### Card per jaluzea (generat automat)

Fiecare jaluzea primește un `vertical-stack` cu două sub-carduri:

```yaml
- type: vertical-stack
  cards:
    # ── Titlu ──────────────────────────────────────────────
    - type: markdown
      content: "### Bucatarie Nord"

    # ── Control + setări ───────────────────────────────────
    - type: entities
      show_header_toggle: false
      state_color: true
      entities:
        - entity: cover.bucatarie_nord # butoane ↑ ■ ↓ automat
          name: "Bucatarie Nord"
        - entity: switch.activ_bucatarie_nord
          name: "Include în automatizare"
        - entity: number.pozitie_deschidere_bucatarie_nord
          name: "Deschidere țintă (%)"
        - type: attribute
          entity: sensor.status_bucatarie_nord
          attribute: stare_automatizare
          name: "Stare automatizare"
          icon: mdi:state-machine
```

> Înlocuiește `bucatarie_nord` cu sufixul real al entității tale cover. Entity ID-urile exacte
> sunt rezolvate automat din registry la generare.

---

## Instalare

### Prin HACS

1. Adaugă repository-ul ca sursă personalizată în HACS → Integrations
2. Caută **Rolls Solar Controller** și instalează
3. Repornește Home Assistant

### Manual

```bash
cp -r custom_components/rolls_ha  <config_dir>/custom_components/
```

Repornește Home Assistant.

---

## Configurare

**Settings → Devices & Services → Add Integration → Rolls Solar Controller**

### Step 1 — Senzori solar

| Câmp                    | Descriere                                                                                     |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| Senzor producție solară | Entitatea care raportează puterea panourilor (W). Ex: `sensor.shelly_em_solar_power`          |
| Senzor putere rețea     | Entitatea care raportează puterea pe contorul de rețea (W). Ex: `sensor.shelly_em_grid_power` |
| Convenție semn          | **➕ Pozitiv = consum din rețea** (Shelly EM standard) sau **➕ Pozitiv = export**            |

> **Shelly EM**: dacă ai un canal pe panouri și unul pe rețea, folosești senzorul de rețea
> cu convenția „pozitiv = consum din rețea" (valoare negativă = injectăm în rețea = surplus).

### Step 2 — Jaluzele

Selectează entitățile `cover` în **ordinea dorită de deschidere**.
Prima jaluzea selectată este prima care se deschide.
Ordinea poate fi schimbată oricând din **Reconfigure**.

### Step 3 — Setări

| Câmp         | Default | Descriere                                                        |
| ------------ | ------- | ---------------------------------------------------------------- |
| Putere motor | 150 W   | Surplusul minim necesar; de obicei consumul motorului în mișcare |

---

## Setări ajustabile

Toate valorile de mai jos pot fi modificate **live** din dashboard (entitățile `number`)
sau din **Configure** (options flow) fără restart:

| Setare                         | Default | Descriere                                                              |
| ------------------------------ | ------- | ---------------------------------------------------------------------- |
| Prag putere motor              | 150 W   | Schimbă pragul global (ex. 200 W dacă motoarele tale consumă mai mult) |
| Poziție deschidere per jaluzea | 100 %   | Deschide la 80% pentru intimitate, 100% pentru lumină maximă           |

### Adăugare jaluzele noi

Oricând poți adăuga (sau elimina) jaluzele fără a reinstala integrarea:

**Settings → Devices & Services → Rolls Solar Controller → Configure →
⋮ → Reconfigure**

Selectezi noua listă de jaluzele în ordinea dorită. Setările existente
(poziție, activ) pentru jaluzelele rămase sunt păstrate.

---

## Teste

Testele nu necesită o instalare completă de Home Assistant.
Modulele HA sunt stub-uite automat prin `tests/conftest.py`.

### Rulare rapidă (recomandat — folosește `uv`)

```bash
uv run --with pytest --with pytest-asyncio python -m pytest tests/ -v
```

### Rulare cu un virtualenv existent

```bash
pip install -r requirements_test.txt
python -m pytest tests/ -v
```

### Structura testelor

```
tests/
  conftest.py                 — stub-uri pentru modulele homeassistant
  test_control_logic.py       — logica de control (S1–S10)
  test_manual_and_reset.py    — detectare manuală (M1–M4) + reset zilnic (R1–R4)
```

### Ce acoperă testele

| Test                                             | Scenariu | Descriere                                             |
| ------------------------------------------------ | -------- | ----------------------------------------------------- |
| `test_s1_deschidere_la_surplus_suficient`        | S1       | Prima jaluzea PENDING se deschide când surplus ≥ prag |
| `test_s1_pozitie_partiala`                       | S1b      | `set_cover_position` folosit când target < 100%       |
| `test_s2_surplus_insuficient_nu_deschide`        | S2       | Surplus < prag → rămâne PENDING                       |
| `test_s2_reset_timer_la_scadere_surplus`         | S2b      | Jaluzea în deschidere + surplus scade → stop_cover + PENDING |
| `test_s3_asteapta_stabilizare`                   | S3       | Surplus suficient → deschidere imediată (fără delay)         |
| `test_s3_actioneaza_dupa_stabilizare`            | S3b      | Surplus prezent → deschide (timer ignorat)                   |
| `test_s4_ordine_deschidere`                      | S4       | Câte una pe rând, nu toate deodată                    |
| `test_s4_sare_peste_auto_opened`                 | S4b      | AUTO_OPENED sărită, continuă cu PENDING               |
| `test_s5_auto_off_nu_actioneaza`                 | S5       | Control global OFF → nicio acțiune                    |
| `test_s6_cover_dezactivata_sarire`               | S6       | Jaluzea dezactivată sărită, continuă cu următoarea    |
| `test_s7_manual_sarita`                          | S7       | MANUAL sărită în coadă                                |
| `test_s8_toate_procesate_stop`                   | S8       | Toate AUTO_OPENED/MANUAL → nicio acțiune              |
| `test_s9_conventie_retea_inversa`                | S9       | Surplus calculat corect cu semn inversat              |
| `test_s10_surplus_virtual_motor_activ`           | S10      | Motor activ adaugă puterea înapoi la surplus          |
| `test_m1_schimbare_manuala_markare`              | M1       | Schimbare fără context coordinator → MANUAL           |
| `test_m2_schimbare_in_grace_period_ignorata`     | M2       | Schimbare în grace period → nu e MANUAL               |
| `test_m3_schimbare_context_coordinator_ignorata` | M3       | Context match → ignorată                              |
| `test_m4_auto_opened_devine_manual_la_inchidere` | M4       | AUTO_OPENED → MANUAL la închidere manuală             |
| `test_r1_reset_midnight_pending`                 | R1       | Toate stările → PENDING la miezul nopții              |
| `test_r2_reset_nu_atinge_dezactivate`            | R2       | Dezactivate nu sunt resetate                          |
| `test_r3_reset_sterge_timer_stabilizare`         | R3       | Timer de stabilizare curățat la reset                 |
| `test_r4_reset_sterge_opening_in_progress`       | R4       | Mișcări în curs și acțiuni curățate la reset          |

---

## Release

### Pași pentru publicarea unui release nou

1. Actualizează versiunea în `custom_components/rolls_ha/manifest.json`:
   ```json
   "version": "1.x.y"
   ```
2. Commit și tag:
   ```bash
   git add .
   git commit -m "Release v1.x.y"
   git tag v1.x.y
   git push origin main --tags
   ```
3. Creează un GitHub Release:
   - Mergi la repository → Releases → Draft a new release
   - Selectează tag-ul `v1.x.y`
   - Titlu: `v1.x.y`
   - Descriere: ce s-a schimbat
   - Publică release-ul

> **Notă:** HACS folosește tag-urile Git ca versiuni. Tag-ul trebuie să coincidă
> exact cu `version` din `manifest.json` (ex. ambele `1.0.0`, nu `v1.0.0` vs `1.0.0`).
