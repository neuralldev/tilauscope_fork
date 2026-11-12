# TilauScope pour Android — version de test

Merci de tester l'application. C'est une version de travail : elle sert à trouver ce qui ne va pas avant une diffusion plus large. Vos retours comptent plus que tout.

## Ce qu'il vous faut

- Une tablette Android 8 ou plus récente (processeur ARM 64 bits, le cas de presque toutes les tablettes récentes).
- Le Bluetooth activé.
- Pour piloter une machine : un Skywalker V2 (Bluetooth). Le Skywalker V1 équipé du module SkyCommand est prévu mais n'a pas encore été essayé : vos retours sont les bienvenus. Sans machine, l'application fonctionne en simulation.

## Installer

1. Téléchargez le fichier `TilauScope-Android-….apk` depuis le dossier partagé.
2. Ouvrez-le sur la tablette. Android demande d'autoriser l'installation d'applications depuis cette source : acceptez pour cette fois.
3. Au premier lancement, autorisez le Bluetooth, les notifications et, si on vous le demande, l'activité en arrière-plan. Sans l'arrière-plan, Android peut interrompre un roast quand l'écran s'éteint : dans les réglages de la tablette, laissez l'application fonctionner en arrière-plan sans restriction.

Les versions suivantes s'installent par-dessus la précédente, sans perdre vos données.

## Ce que l'application sait faire

### La machine
- Liaison Bluetooth avec le Skywalker V2 : le brûleur est vérifié à 0 à chaque connexion, avant tout autre ordre.
- Vérification de la liaison depuis les réglages : températures en direct, air relevé quelques secondes, puis arrêt de la machine.
- Préchauffe automatique (TilauPID) jusqu'à la température de charge ; toucher le brûleur la met en pause, un bouton la reprend. Elle apprend de vos préchauffes.
- Fin de roast : refroidissement jusqu'à 50 °C puis arrêt de la machine. Un nouveau roast lancé pendant le refroidissement (back-to-back) reprend la machine, et la préchauffe repart de la température atteinte.
- Coupure de liaison : reconnexion automatique, brûleur maintenu à 0 au retour, curseurs de la machine grisés pendant la coupure.

### Le roast
- Courbes des températures des grains et du tambour, vitesse de montée (RoR), temps du roast tenu même écran éteint.
- Curseurs brûleur, air et tambour (et extracteur s'il est présent) avec la valeur confirmée par la machine ; choix rapide d'une valeur sur une roue ; réglages tracés sous la courbe.
- Jalons Charge, Fin de séchage, Premier crack et Vidage à toucher, avec annulation.
- Détection automatique de la Charge, de la Fin de séchage et du Premier crack (ce dernier avec le compteur de cracks de la sonde TilauAmbient).
- Trois façons de roaster : à la main, en suivant le plan, ou en suivant un roast précédent dont les réglages sont rejoués.
- Alarmes : vos listes d'alarmes d'Artisan importées, modifiables sur la tablette, déclenchées comme sur l'ordinateur.
- Fin de roast : poids torréfié et perte en poids, couleur des grains, énergie consommée, étiquette imprimée.
- Un roast interrompu par la fermeture de l'application est retrouvé à la réouverture.
- Simulation : rejouer un roast enregistré, à vitesse 1×, 2× ou 8×, avec pause, sans aucun appareil connecté.
- Températures en °C ou en °F.

### Le café et le plan
- BeanCave : vos cafés verts, leur fiche et leur modification, le stock diminué du poids roasté, les dégustations, le roast de référence ★.
- Roast Setup : poids du vert, densité, humidité, température des grains, titre du roast, préchauffe.
- Le plan du roast : niveau de torréfaction, usage (filtre, omni, espresso), température et temps de chaque étape, appris de vos roasts du même café.
- Onglet Roasts : la liste de vos roasts (tri, filtre), le détail avec la courbe, les jalons et l'énergie, le partage, la suppression.
- Échange avec TilauScope sur ordinateur : import et envoi de la BeanCave et des roasts ; chaque roast est un vrai fichier Artisan que l'ordinateur ouvre comme les siens.

### Les accessoires
- Balance Acaia (essayée sur une Lunar) : pesée du vert et du torréfié, poids en direct sur l'écran de roast.
- Extracteur DiFluid AirWave : puissance, vitesse, mode, températures d'entrée et du catalyseur.
- Sonde TilauAmbient : température, humidité et pression de la pièce, notées à la Charge ; compteur de cracks.
- Lecteur de couleur RoastSee C1 : couleur en grains et moulue, gardées séparément.
- RoastSee AquaGauge : activité de l'eau du café vert.
- Imprimante Niimbot B21S : étiquette du roast.
- Capteurs MQTT : conditions de la pièce et puissance électrique de la machine et de l'extracteur, pour l'énergie du roast.

## Avant le premier roast

- L'assistant de premier lancement vous fait choisir votre machine et vérifier la liaison : la tablette lit les températures, fait varier l'air quelques secondes, puis arrête la machine.
- Vos accessoires se déclarent dans Settings › Devices : balance Acaia, extracteur DiFluid AirWave, sonde TilauAmbient, lecteur de couleur, mesureur d'activité de l'eau, imprimante d'étiquettes Niimbot B21S.
- Votre BeanCave peut venir de TilauScope sur ordinateur : Settings › BeanCave, « Import the BeanCave… ».

## Pendant le roast : la sécurité d'abord

- **Ne laissez jamais la machine sans surveillance.** C'est une version de test.
- Si la liaison avec la machine se coupe, la machine coupe sa chauffe d'elle-même. À la reconnexion, le brûleur reste à 0 : c'est à vous de le relever. Pendant la coupure, le brûleur, l'air et le tambour sont grisés.
- Le bouton Stop rouge arrête tout.

## Ce que nous aimerions que vous testiez

- Un roast complet, du préchauffage au refroidissement, sur votre machine.
- La pesée du vert avec la balance (pastille « Green »), et le plan proposé dans Roast Setup.
- Un roast qui suit un roast précédent (« A roast »), et un roast qui suit le plan.
- Le fichier du roast ouvert ensuite dans TilauScope sur ordinateur : il doit s'y retrouver comme un roast fait sur l'ordinateur.
- Ce qui se passe si vous éteignez l'écran, changez d'application ou si le Bluetooth décroche pendant un roast.

## Signaler un problème

Envoyez votre demande sur le canal discord :
- ce que vous faisiez, ce que vous attendiez, ce qui s'est passé ;
- une capture d'écran si possible ;
- la version de l'application (nom du fichier installé, par exemple `0.1.0-2`) ;
- **le journal de l'application** : Settings › General › Diagnostic log, bouton de partage. Il raconte ce que l'application a fait (liaisons, ordres envoyés à la machine, erreurs) ; il ne contient aucun mot de passe.

## À savoir

- Cette version de test est réservée aux testeurs : merci de ne pas la diffuser.
- Elle reprend des parties d'Artisan Roaster Scope, sous licence libre : le code source de cette version est disponible sur demande.
