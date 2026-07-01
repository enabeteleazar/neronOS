# Compatibilité Oblivia

L’implémentation métier officielle se trouve dans `memory.oblivia`.

Ce package Core ne contient que les façades nécessaires aux anciens imports et
aux routes API historiques. Toute opération est déléguée au Provider Registry
et transportée via A2A.
