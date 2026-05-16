# Urban Duel Online

Jeu de cartes 1v1 en Python 3.12 avec :

- moteur de règles pur dans `core/` ;
- backend FastAPI autoritaire dans `backend/` ;
- communication temps réel WebSocket validée côté serveur ;
- gestion de room/matchmaking dans `rooms/` ;
- frontend navigateur léger en HTML/CSS/JS dans `frontend/` ;
- prototype Pygame local toujours disponible dans `ui/` ;
- draft partagé en début de match ;
- roster actif de 30 personnages ;
- clans, bonus de clan, étoiles et pouvoirs data-driven.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Lancer le backend

```bash
python -m backend.main
```

Backend local :

- WebSocket : `ws://127.0.0.1:8000/ws`
- Healthcheck : `http://127.0.0.1:8000/health`
- Frontend servi par FastAPI : `http://127.0.0.1:8000/`

## Lancer le frontend

```bash
python -m frontend.server
```

Frontend local :

- `http://127.0.0.1:4173`

Ce serveur frontend separe reste disponible pour le developpement local. En deploiement Render, il n'est pas utilise : FastAPI sert directement `frontend/` et `assets/`.

## Deploiement Render

Le projet est pret pour un seul Web Service Render :

- FastAPI sert le frontend statique depuis `frontend/` ;
- les fichiers `assets/` sont exposes sous `/assets/...` ;
- le WebSocket reste disponible sur `/ws` dans la meme application ;
- le serveur ecoute `0.0.0.0` et lit le port depuis la variable d'environnement `PORT`.

Valeurs a mettre dans Render :

- Build Command : `pip install -r requirements-render.txt`
- Start Command : `python -m backend.main`
- Health Check Path : `/health`

Variable d'environnement conseillee :

- `PYTHON_VERSION` : `3.12.3`

Render fournit automatiquement `PORT`. Le fichier `render.yaml` contient la meme configuration si tu choisis de creer le service via Blueprint.

`requirements-render.txt` exclut volontairement `pygame`, qui sert seulement au prototype local. Render n'a donc pas besoin des bibliotheques systeme SDL. Il installe `uvicorn[standard]` pour inclure le support WebSocket en production.

## Prototype local Pygame

```bash
python main.py
```

## Architecture

La séparation est stricte :

- `core/` : règles, modèles, moteur, sérialisation ;
- `net/` : protocole JSON Pydantic et passerelle WebSocket ;
- `rooms/` : room manager, état de partie en ligne, matchmaking simple ;
- `backend/` : application FastAPI et point d’entrée ;
- `frontend/` : interface web, aucun calcul métier ;
- `tests/` : moteur + WebSockets.

Le serveur reste la seule source de vérité :

- le frontend envoie des intentions ;
- le backend valide ;
- le backend calcule ;
- le backend diffuse l’état officiel.

## Machines d'état

Machine d'état de partie centralisée dans [rooms/state_machine.py](C:/Users/Mathiu/Documents/URBAN/rooms/state_machine.py:1) :

- `waiting_for_players`
- `round_selection`
- `round_locked`
- `round_resolution`
- `game_over`

Machine d'état joueur centralisée au même endroit :

- `connected`
- `in_lobby`
- `in_room`
- `selecting`
- `locked`
- `disconnected`

La passerelle WebSocket ne décide aucune transition métier ; elle délègue au service central.

## Parcours produit

1. Un joueur ouvre le frontend et se connecte au WebSocket.
2. Il crée une room ou rejoint une room existante.
3. Quand le second joueur rejoint, le serveur ouvre un draft partagé de 10 cartes.
4. Chaque joueur compose une équipe de 4 cartes avec un total d’étoiles `<= 8`.
5. Une fois les deux équipes verrouillées, la partie démarre.
6. Chaque joueur choisit ensuite une carte et un nombre de pills.
7. Le backend n’expose jamais les pills adverses avant la résolution.
8. Le joueur qui a l’initiative confirme d’abord ; sa carte devient visible pour l’autre.
9. Quand les deux confirmations sont reçues, le serveur résout le round.
10. Le serveur diffuse le résultat officiel puis, en fin de partie, le gagnant.
11. En cas de déconnexion pendant la partie ou pendant le draft, l’adversaire gagne par abandon ; en lobby, la session peut être reprise si le token de session est encore valide.

## Protocole WebSocket JSON

Tous les messages utilisent l’enveloppe suivante :

```json
{
  "type": "message_type",
  "room_id": "ABC123",
  "player_id": 1,
  "timestamp": "2026-04-19T16:00:00Z",
  "payload": {}
}
```

Les schémas Pydantic sont définis dans [net/protocol.py](C:/Users/Mathiu/Documents/URBAN/net/protocol.py:1).

### Client -> Serveur

- `create_room`
- `join_room`
- `select_card`
- `set_pills`
- `confirm_selection`
- `ping`
- `request_state`

Exemples :

```json
{
  "type": "create_room",
  "payload": {
    "player_name": "Alice"
  }
}
```

```json
{
  "type": "join_room",
  "room_id": "ABC123",
  "payload": {
    "player_name": "Bob"
  }
}
```

```json
{
  "type": "select_card",
  "room_id": "ABC123",
  "player_id": 1,
  "payload": {
    "card_id": "blade"
  }
}
```

```json
{
  "type": "set_pills",
  "room_id": "ABC123",
  "player_id": 1,
  "payload": {
    "pills": 3
  }
}
```

```json
{
  "type": "confirm_selection",
  "room_id": "ABC123",
  "player_id": 1,
  "payload": {}
}
```

### Serveur -> Client

- `room_created`
- `room_joined`
- `player_joined`
- `game_started`
- `state_snapshot`
- `player_ready`
- `round_resolved`
- `game_finished`
- `opponent_disconnected`
- `error`

Message supplémentaire utile :

- `pong`

## Tests

Suite complète :

```bash
python -m pytest
```

Tests WebSocket uniquement :

```bash
python -m pytest tests/test_websocket_api.py
```

Draft + effets :

```bash
python -m pytest tests/test_draft.py tests/test_effects.py
```

## Notes de développement

- le frontend ne connaît aucune règle de résolution ;
- les messages utilisateur sont validés par Pydantic ;
- la room réseau utilise un backend autoritaire en mémoire ;
- les cartes et illustrations viennent de `data/cards.json` et `assets/`.
