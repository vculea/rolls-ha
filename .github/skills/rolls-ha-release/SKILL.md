---
name: rolls-ha-release
description: "Pregătește și publică release-uri pentru integrarea Home Assistant Rolls Solar Controller: verifică schimbările locale, actualizează versiunea manifestului, rulează testele, face commit, tag și push la branch și tag, apoi generează sumarul GitHub Release. Folosește pentru release, version bump, changelog, release notes sau publicarea unei versiuni noi."
argument-hint: "Versiunea dorită sau 'următorul patch release'"
user-invocable: true
---

# Rolls HA Release

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

## Procedură

1. Verifică `git status`, istoricul recent și versiunea din manifest. Citește
   diff-ul local înainte de a decide ce intră în release; nu suprascrie și nu
   elimina modificări existente ale utilizatorului.
2. Stabilește versiunea. Folosește patch pentru bug fix-uri, minor pentru
   funcționalitate compatibilă și major pentru schimbări incompatibile. Confirmă
   că tag-ul dorit nu există deja.
3. Rulează suita proiectului:

   ```bash
   uv run --with pytest --with pytest-asyncio python -m pytest tests/ -v
   ```

   Oprește pregătirea dacă testele eșuează. Notează separat warning-urile care nu
   blochează testele.

4. Actualizează doar câmpul `version` din manifest și păstrează JSON-ul valid.
   Include în notele release-ului modificările efective din diff și commit-urile
   de la ultimul tag relevant; nu inventa funcționalități.
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

6. Revizuiește diff-ul complet și pregătește sumarul release-ului, dar nu
   aștepta aprobarea utilizatorului. Include schimbările intenționate pentru
   release din cod, teste, documentație și manifest; lasă fișierele fără legătură,
   secrete și artefactele generate în afara commit-ului.
7. Verifică indexul Git înainte de staging. Nu include și nu elimina modificări
   staged preexistente care nu fac parte clar din release. Dacă nu poți separa
   sigur schimbările release-ului de lucru fără legătură, oprește-te și raportează
   blocajul fără să pierzi modificări. Altfel, stage-uiește explicit fișierele
   release-ului și creează un commit descriptiv, de exemplu
   `release: vX.Y.Z - descriere scurtă`. Dacă acel commit există deja, nu-l repeta.
8. După commit, creează tag-ul `vX.Y.Z` pe commit-ul release-ului. Apoi împinge
   branch-ul curent și tag-ul la `origin`, fără force-push:

   ```bash
   git tag vX.Y.Z
   git push origin <branch-curent>
   git push origin vX.Y.Z
   ```

   Ordinea corectă este commit, tag, push branch, push tag. Verifică apoi că
   branch-ul și tag-ul sunt vizibile pe remote și că tag-ul pointează la commit-ul
   release-ului. Dacă release-ul este deja comis, nu repeta commit-ul; dacă tag-ul
   există deja, nu-l muta și nu-l suprascrie. Dacă testele eșuează, tag-ul
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
