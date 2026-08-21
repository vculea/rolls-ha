---
name: rolls-ha-release
description: "Pregătește release-uri pentru integrarea Home Assistant Rolls Solar Controller: verifică schimbările locale, actualizează versiunea manifestului, rulează testele, generează notele GitHub Release și validează tag-ul. Folosește pentru release, version bump, changelog, release notes sau publicarea unei versiuni noi."
argument-hint: "Versiunea dorită sau 'următorul patch release'"
user-invocable: true
---

# Rolls HA Release

## Scop

Pregătește un release reproductibil pentru acest repository fără să publice
automat modificări sau să șteargă lucru local. Release-ul trebuie să păstreze
aceeași versiune în `custom_components/rolls_ha/manifest.json` și în tag-ul Git
cu prefix `v` (de exemplu, versiunea `1.3.17` folosește tag-ul `v1.3.17`).

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

6. Arată utilizatorului diff-ul și sumarul înainte de commit. Nu executa
   `git commit`, `git tag` sau `git push` fără cerere explicită.
7. După confirmare, comenzile de publicare sunt:

   ```bash
   git add custom_components/rolls_ha/manifest.json
   git commit -m "release: vX.Y.Z — descriere scurtă"
   git tag vX.Y.Z
   git push origin main --tags
   ```

## Criterii de finalizare

- manifestul conține versiunea release-ului;
- testele sunt trecute sau rezultatul este raportat clar;
- tag-ul nu exista înainte de pregătire;
- sumarul nu conține afirmații neacoperite de diff sau teste;
- modificările utilizatorului și fișierele fără legătură rămân intacte.
