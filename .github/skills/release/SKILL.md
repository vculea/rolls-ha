---
name: release
description: "Pregătește și publică release-uri pentru integrarea Home Assistant Rolls Solar Controller: verifică schimbările locale, actualizează versiunea manifestului, rulează testele, face commit, tag și push la branch și tag, apoi generează sumarul GitHub Release. Folosește pentru release, version bump, changelog, release notes sau publicarea unei versiuni noi."
argument-hint: "Versiunea dorită sau 'următorul patch release'"
user-invocable: true
---

# Release

## Scop

Pregătește și publică un release reproductibil pentru acest repository. O cerere
de release înseamnă implicit: teste, commit al schimbărilor release-ului, tag,
push la branch-ul curent și push la tag, apoi sumarul pentru GitHub Release. Nu
cere confirmări intermediare. Publică numai dacă utilizatorul cere explicit
„doar pregătire” sau „fără publicare”. Nu șterge și nu suprascrie modificări
locale și nu include automat fișiere fără legătură, secrete sau artefacte
generate. Release-ul trebuie să păstreze aceeași versiune în
`custom_components/rolls_ha/manifest.json` și în tag-ul Git cu prefix `v` (de
exemplu, versiunea `1.3.17` folosește tag-ul `v1.3.17`).

Pentru a reduce consumul de context și apelurile inutile, grupează verificările
read-only într-un singur preflight, citește doar fișierele din diff și manifestul
și nu repeta verificări dacă starea nu s-a schimbat. Nu folosi subagenți pentru
acest flux. Păstrează însă verificările de test, index, tag și remote de mai jos.

## Procedură

1. Într-un singur preflight, verifică starea, istoricul, ultimul tag și toate
   diferențele locale; citește și manifestul. De exemplu:

   ```bash
   git status --short --branch
   git log -5 --oneline --decorate
   git describe --tags --abbrev=0
   git diff --stat
   git diff
   git diff --cached --stat
   git diff --cached
   ```

   Citește doar fișierele din diff și manifestul, nu scana repository-ul în
   întregime. Nu suprascrie și nu elimina modificări existente ale utilizatorului.

2. Stabilește versiunea. Folosește patch pentru bug fix-uri, minor pentru
   funcționalitate compatibilă și major pentru schimbări incompatibile. Confirmă
   o singură dată că tag-ul dorit nu există nici local, nici pe `origin`:

   ```bash
   git tag --list vX.Y.Z
   git ls-remote --tags origin refs/tags/vX.Y.Z
   ```

   Dacă tag-ul există deja, nu-l muta și nu-l suprascrie.

3. Rulează suita proiectului:

   ```bash
   uv run --with pytest --with pytest-asyncio python -m pytest tests/ -q
   ```

   Oprește pregătirea dacă testele eșuează. Notează rezultatul real și warning-urile
   separat; nu investiga sau modifica warning-uri fără legătură cu release-ul.

4. Actualizează doar câmpul `version` din manifest și păstrează JSON-ul valid.
   Validează-l cu interpreterul proiectului, nu cu `python` direct:

   ```bash
   uv run python -m json.tool custom_components/rolls_ha/manifest.json
   ```

   Testele nu trebuie rerulate doar pentru schimbarea numărului de versiune; dacă
   se modifică ulterior codul sau testele, rulează-le din nou. Include în notele
   release-ului modificările efective din diff și commit-urile de la ultimul tag
   relevant; nu inventa funcționalități.

5. Generează un sumar scurt pentru pagina GitHub Release în formatul:

   ```markdown
   ## Ce s-a schimbat

   - ...

   ## Verificare

   - `23 passed` (sau rezultatul real al suitei)

   ## Instalare

   Actualizează integrarea din HACS sau copiază folderul `custom_components/rolls_ha`.
   Repornește Home Assistant dacă este necesar.
   ```

6. Verifică `git diff --check`. Înainte de staging, inspectează indexul; nu include
   și nu elimina modificări staged preexistente care nu fac parte din release.
   Dacă ele ating aceleași fișiere ca release-ul sau nu le poți separa sigur,
   oprește-te și raportează blocajul fără să pierzi modificări. Dacă sunt în alte
   fișiere, păstrează-le staged și folosește `git commit --only` la pasul 7.
7. Stage-uiește explicit numai fișierele release-ului. Revizuiește o singură dată
   diff-ul staged pentru acele fișiere și verifică-l:

   ```bash
   git diff --cached --check -- <fișiere-release>
   git diff --cached -- <fișiere-release>
   ```

   Include doar schimbările intenționate din cod, teste, documentație și manifest;
   exclude fișiere fără legătură, secrete și artefacte generate. Creează un commit
   descriptiv, de exemplu `release: vX.Y.Z - descriere scurtă`. Dacă indexul avea
   alte fișiere staged, folosește `git commit --only -m "release: vX.Y.Z - descriere scurtă" -- <fișiere-release>` ca să nu le incluzi; altfel folosește commit normal. Dacă acel commit există deja, nu-l repeta.

8. După commit, creează tag-ul `vX.Y.Z` pe commit-ul release-ului. Apoi împinge
   branch-ul curent și tag-ul la `origin`, fără force-push:

   ```bash
   git tag vX.Y.Z
   git push origin <branch-curent>
   git push origin vX.Y.Z
   ```

   Ordinea corectă este commit, tag, push branch, push tag. Verifică apoi că
   branch-ul și tag-ul sunt vizibile pe remote și că tag-ul pointează la commit-ul
   release-ului prin compararea hash-urilor remote cu commit-ul release-ului.
   Dacă release-ul este deja comis, nu repeta commit-ul; dacă tag-ul există deja,
   nu-l muta și nu-l suprascrie. Dacă testele eșuează, tag-ul
   aparține altui commit sau push-ul eșuează, oprește pașii rămași și raportează
   exact ce a fost deja publicat și ce nu.

9. După publicarea reușită, afișează sumarul GitHub Release în formatul de la
   pasul 5, împreună cu rezultatul testelor, avertismentele, commit-ul și tag-ul.
   Pentru cererea explicită „doar pregătire” sau „fără publicare”, nu face commit,
   tag sau push și prezintă sumarul după validări.

## Execuție consemnată

- 2026-10-05: tag-ul `v1.3.18` a fost creat și publicat la cererea utilizatorului.

## Criterii de finalizare

- manifestul conține versiunea release-ului;
- testele sunt trecute sau rezultatul este raportat clar;
- commit-ul release-ului, tag-ul și branch-ul au fost împinse și verificate pe remote;
- sumarul nu conține afirmații neacoperite de diff sau teste;
- modificările utilizatorului și fișierele fără legătură rămân intacte.
