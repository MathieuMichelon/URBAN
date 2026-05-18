const SESSION_STORAGE_KEY = "urban_duel_session";
const OVERLOAD_PILL_COST = 2;
const OVERLOAD_DAMAGE_BONUS = 3;

const state = {
  socket: null,
  roomId: null,
  playerId: null,
  sessionToken: null,
  snapshot: null,
  interaction: {
    selectedCardId: null,
    pillsPreview: 0,
    overloadPreview: false,
    confirmEnabled: false,
  },
  resolution: {
    active: false,
    roundResult: null,
    step: "idle",
    timeoutIds: [],
  },
};

const elements = {
  wsUrl: document.querySelector("#ws-url"),
  playerName: document.querySelector("#player-name"),
  roomId: document.querySelector("#room-id"),
  connectButton: document.querySelector("#connect-button"),
  createButton: document.querySelector("#create-button"),
  joinButton: document.querySelector("#join-button"),
  requestStateButton: document.querySelector("#request-state-button"),
  confirmButton: document.querySelector("#confirm-button"),
  pingButton: document.querySelector("#ping-button"),
  pillsInput: document.querySelector("#pills-input"),
  pillsValue: document.querySelector("#pills-value"),
  overloadInput: document.querySelector("#overload-input"),
  overloadMeta: document.querySelector("#overload-meta"),
  connectionStatus: document.querySelector("#connection-status"),
  roomStatus: document.querySelector("#room-status"),
  summaryContent: document.querySelector("#summary-content"),
  draftPanel: document.querySelector("#draft-panel"),
  draftStatus: document.querySelector("#draft-status"),
  draftOffer: document.querySelector("#draft-offer"),
  draftTeam: document.querySelector("#draft-team"),
  draftTeamMeta: document.querySelector("#draft-team-meta"),
  draftTeamSummary: document.querySelector("#draft-team-summary"),
  draftLockButton: document.querySelector("#draft-lock-button"),
  matchShell: document.querySelector("#match-shell"),
  roundValue: document.querySelector("#round-value"),
  initiativeValue: document.querySelector("#initiative-value"),
  matchStateValue: document.querySelector("#match-state-value"),
  selectionInfo: document.querySelector("#selection-info"),
  selectionStage: document.querySelector("#selection-stage"),
  selectionDetail: document.querySelector("#selection-detail"),
  selectionControls: document.querySelector("#selection-controls"),
  battleResolution: document.querySelector("#battle-resolution"),
  matchEndPanel: document.querySelector("#match-end-panel"),
  matchEndTitle: document.querySelector("#match-end-title"),
  matchEndReason: document.querySelector("#match-end-reason"),
  matchEndScore: document.querySelector("#match-end-score"),
  matchEndRematchStatus: document.querySelector("#match-end-rematch-status"),
  rematchButton: document.querySelector("#rematch-button"),
  returnHomeButtonInline: document.querySelector("#return-home-button-inline"),
  playerZone: document.querySelector(".player-zone"),
  opponentZone: document.querySelector(".opponent-zone"),
  localHand: document.querySelector("#local-hand"),
  opponentHand: document.querySelector("#opponent-hand"),
  playerIdentity: document.querySelector("#player-identity"),
  playerStatus: document.querySelector("#player-status"),
  opponentIdentity: document.querySelector("#opponent-identity"),
  opponentStatus: document.querySelector("#opponent-status"),
  lobbyPlayers: document.querySelector("#lobby-players"),
  lobbyRoomId: document.querySelector("#lobby-room-id"),
  lobbyMatchState: document.querySelector("#lobby-match-state"),
  gameBanner: document.querySelector("#game-banner"),
  endBanner: document.querySelector("#end-banner"),
  endSummary: document.querySelector("#end-summary"),
  eventLog: document.querySelector("#event-log"),
  errorBanner: document.querySelector("#error-banner"),
  homeView: document.querySelector("#home-view"),
  lobbyView: document.querySelector("#lobby-view"),
  gameView: document.querySelector("#game-view"),
  endView: document.querySelector("#end-view"),
  returnHomeButton: document.querySelector("#return-home-button"),
  resetSelectionButton: document.querySelector("#reset-selection-button"),
  pillsControl: document.querySelector("#pills-control"),
};

function ensureMatchSideChrome() {
  const sides = [
    { element: elements.playerZone, sideClass: "local-side", label: "TES CARTES" },
    { element: elements.opponentZone, sideClass: "opponent-side", label: "CARTES ADVERSAIRE" },
  ];

  sides.forEach(({ element, sideClass, label }) => {
    if (!element) {
      return;
    }

    element.classList.add(sideClass);
    let sideLabel = element.querySelector(":scope > .side-label");
    if (!sideLabel) {
      sideLabel = document.createElement("div");
      sideLabel.className = "side-label";
      element.insertBefore(sideLabel, element.firstChild);
    }
    sideLabel.textContent = label;
  });
}

function syncMatchSideState(localPlayer, opponent) {
  const pairs = [
    { element: elements.playerZone, player: localPlayer },
    { element: elements.opponentZone, player: opponent },
  ];

  pairs.forEach(({ element, player }) => {
    if (!element) {
      return;
    }

    element.classList.toggle("side-must-act", player?.player_state === "selecting");
    element.classList.toggle("side-locked", Boolean(player?.ready));
  });
}

function buildDefaultWebSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const hostname = window.location.hostname || "127.0.0.1";
  const host = window.location.port === "4173"
    ? `${hostname}:8000`
    : (window.location.host || `${hostname}:8000`);
  return `${protocol}//${host}/ws`;
}

function addLog(message) {
  const entry = document.createElement("div");
  entry.className = "event-entry";
  entry.textContent = `${new Date().toLocaleTimeString()} - ${message}`;
  elements.eventLog.prepend(entry);
}

function showError(message) {
  elements.errorBanner.textContent = message;
  elements.errorBanner.classList.remove("hidden");
}

function clearError() {
  elements.errorBanner.textContent = "";
  elements.errorBanner.classList.add("hidden");
}

function persistSession() {
  if (!state.roomId || !state.playerId || !state.sessionToken) {
    return;
  }
  localStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({
      roomId: state.roomId,
      playerId: state.playerId,
      playerName: elements.playerName.value,
      sessionToken: state.sessionToken,
    }),
  );
}

function loadPersistedSession() {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function clearPersistedSession() {
  localStorage.removeItem(SESSION_STORAGE_KEY);
}

function resetMatchInteraction() {
  state.interaction.selectedCardId = null;
  state.interaction.pillsPreview = 0;
  state.interaction.overloadPreview = false;
  state.interaction.confirmEnabled = false;
}

function clearRoundResolutionAnimation() {
  state.resolution.timeoutIds.forEach((timeoutId) => window.clearTimeout(timeoutId));
  state.resolution.active = false;
  state.resolution.roundResult = null;
  state.resolution.step = "idle";
  state.resolution.timeoutIds = [];
}

function startRoundResolutionAnimation(roundResult) {
  clearRoundResolutionAnimation();
  state.resolution.active = true;
  state.resolution.roundResult = roundResult;
  state.resolution.step = "intro";

  const steps = [
    [2000, "pills"],
    [4000, "attack"],
    [6000, "winner"],
    [8000, "effects"],
    [10800, "done"],
  ];

  state.resolution.timeoutIds = steps.map(([delay, step]) => window.setTimeout(() => {
    if (step === "done") {
      clearRoundResolutionAnimation();
    } else {
      state.resolution.step = step;
    }
    render();
  }, delay));

  render();
}

function maxAttackPillsFor(localPlayer, overload = state.interaction.overloadPreview) {
  const availablePills = localPlayer?.pills ?? 0;
  return Math.max(0, availablePills - (overload ? OVERLOAD_PILL_COST : 0));
}

function clampInteractionPills(localPlayer) {
  const maxPills = maxAttackPillsFor(localPlayer);
  state.interaction.pillsPreview = Math.max(0, Math.min(maxPills, state.interaction.pillsPreview));
}

function normalizeSelectionInteraction(localPlayer, selectedCard = null) {
  const canAffordOverload = Boolean(selectedCard) && (localPlayer?.pills ?? 0) >= OVERLOAD_PILL_COST;
  if (!canAffordOverload) {
    state.interaction.overloadPreview = false;
  }
  clampInteractionPills(localPlayer);
}

function buildSelectionProjection(localPlayer, selectedCard) {
  const attackPills = selectedCard ? state.interaction.pillsPreview : 0;
  const overloadActive = Boolean(selectedCard && state.interaction.overloadPreview);
  const overloadCost = overloadActive ? OVERLOAD_PILL_COST : 0;
  const totalCost = attackPills + overloadCost;

  return {
    selectedName: selectedCard?.name ?? "aucune",
    projectedAttack: selectedCard ? selectedCard.power * (attackPills + 1) : "-",
    projectedDamage: selectedCard ? selectedCard.damage + (overloadActive ? OVERLOAD_DAMAGE_BONUS : 0) : "-",
    attackPills,
    overloadCost,
    totalCost,
    availablePills: localPlayer?.pills ?? 0,
    overloadActive,
    bonusState: selectedCard ? (selectedCard.bonus_active ? "actif" : "inactif") : "-",
  };
}

function playerLabel(player) {
  if (!player) {
    return "Joueur inconnu";
  }
  return `${player.name || `Joueur ${player.player_id}`} (P${player.player_id})`;
}

function buildGameOverSummary(snapshot) {
  const players = snapshot?.players ?? [];
  const localPlayer = players.find((player) => player.player_id === snapshot?.local_player_id);
  const winner = players.find((player) => player.player_id === snapshot?.winner_id);
  const loser = players.find((player) => player.player_id !== snapshot?.winner_id);
  const player1 = players.find((player) => player.player_id === 1);
  const player2 = players.find((player) => player.player_id === 2);
  const isLocalWinner = snapshot?.winner_id !== null && snapshot?.winner_id === snapshot?.local_player_id;
  const title = snapshot?.winner_id === null
    ? "Match nul"
    : isLocalWinner ? "Victoire" : "Défaite";

  let reason = "Partie terminée.";
  if (snapshot?.end_reason === "opponent_disconnected") {
    reason = winner
      ? `${playerLabel(winner)} gagne par abandon : l'adversaire s'est déconnecté.`
      : "Partie terminée par déconnexion.";
  } else if (snapshot?.end_reason === "knockout") {
    reason = loser
      ? `KO de ${playerLabel(loser)}. ${winner ? playerLabel(winner) : "Le gagnant"} remporte la partie.`
      : "Victoire par KO.";
  } else if (snapshot?.end_reason === "score") {
    reason = winner && player1 && player2
      ? `${playerLabel(winner)} gagne aux PV : ${player1.hit_points ?? 0} PV contre ${player2.hit_points ?? 0} PV.`
      : "Victoire aux PV.";
  } else if (snapshot?.winner_id === null) {
    reason = player1 && player2
      ? `Egalité finale : ${player1.hit_points ?? 0} PV contre ${player2.hit_points ?? 0} PV.`
      : "Egalité finale.";
  }

  const scoreLines = players.map((player) => ({
    label: player.player_id === localPlayer?.player_id ? "Toi" : "Adversaire",
    name: playerLabel(player),
    hp: player.hit_points ?? "-",
    pills: player.pills ?? "-",
    isWinner: player.player_id === snapshot?.winner_id,
  }));

  const readyIds = snapshot?.rematch_ready_player_ids ?? [];
  const localReady = readyIds.includes(snapshot?.local_player_id);
  const opponent = players.find((player) => player.player_id !== snapshot?.local_player_id);
  const opponentReady = opponent ? readyIds.includes(opponent.player_id) : false;
  const canRequestRematch = snapshot?.match_state === "game_over"
    && players.length === 2
    && players.every((player) => player.connected)
    && !localReady;
  const rematchStatus = players.length < 2
    ? "Revanche indisponible : il manque un joueur."
    : !players.every((player) => player.connected)
      ? "Revanche indisponible tant que l'autre joueur est déconnecté."
      : localReady && opponentReady
        ? "Les deux joueurs ont demandé une revanche. Nouveau draft en cours..."
        : localReady
          ? "Revanche demandée. En attente de l'autre joueur."
          : opponentReady
            ? "L'adversaire veut rejouer. Clique sur Rejouer pour relancer."
            : "Les deux joueurs peuvent relancer directement une partie dans cette room.";

  return { title, reason, scoreLines, rematchStatus, canRequestRematch };
}

function getTurnStatusMessage(snapshot, localPlayer, opponent) {
  if (!snapshot) {
    return { text: "En attente de la partie.", tone: "waiting" };
  }

  const matchState = snapshot.match_state;
  if (matchState === "waiting_for_players") {
    return { text: "En attente d'un second joueur.", tone: "waiting" };
  }

  if (matchState === "drafting") {
    const lockedCount = snapshot.draft_locked_player_ids?.length ?? 0;
    return {
      text: `Draft en cours : compose 4 cartes pour 8 stars max. Equipes verrouillées : ${lockedCount}/2.`,
      tone: "your-turn",
    };
  }

  if (matchState === "round_resolution" || state.resolution.active) {
    return { text: "Les deux joueurs ont confirmé, résolution du round...", tone: "resolving" };
  }

  if (matchState === "game_over") {
    const summary = buildGameOverSummary(snapshot);
    return { text: summary.reason, tone: snapshot.winner_id === snapshot.local_player_id ? "your-turn" : "waiting" };
  }

  const localReady = Boolean(localPlayer?.ready);
  const opponentReady = Boolean(opponent?.ready);
  const opponentCardRevealed = Boolean(opponent?.draft_card_id);
  const localSelected = Boolean(state.interaction.selectedCardId || localPlayer?.draft_card_id);
  const localCanSelect = localPlayer?.player_state === "selecting";
  const localHasInitiative = snapshot.initiative_player_id === snapshot.local_player_id;

  if (localReady && opponentReady) {
    return { text: "Les deux joueurs ont confirmé, résolution du round...", tone: "resolving" };
  }

  if (localReady) {
    return { text: "En attente du choix adverse. Ta carte est verrouillée côté serveur.", tone: "waiting" };
  }

  if (opponentReady && opponentCardRevealed) {
    return {
      text: "Carte adverse révélée : l'adversaire a confirmé, à toi de répondre.",
      tone: "revealed",
    };
  }

  if (opponentReady) {
    return {
      text: "L'adversaire a choisi une carte. Elle reste cachée tant qu'elle n'est pas révélée par l'initiative.",
      tone: "opponent-ready",
    };
  }

  if (!localCanSelect && !localHasInitiative) {
    return {
      text: "En attente du choix adverse : l'adversaire a l'initiative et doit confirmer en premier.",
      tone: "waiting",
    };
  }

  if (localSelected) {
    return {
      text: localHasInitiative ? "Tu dois confirmer ton choix. Tu as l'initiative." : "Tu dois confirmer ton choix.",
      tone: "your-turn",
    };
  }

  if (localCanSelect) {
    return {
      text: localHasInitiative ? "À toi de choisir une carte. Tu as l'initiative." : "À toi de choisir une carte.",
      tone: "your-turn",
    };
  }

  return { text: "En attente du choix adverse.", tone: "waiting" };
}

function formatTotalPillCost(projection) {
  if (!projection.overloadActive) {
    return String(projection.attackPills);
  }
  return `${projection.attackPills} + ${projection.overloadCost} = ${projection.totalCost}`;
}

function syncInteractionWithSnapshot() {
  const snapshot = state.snapshot;
  if (!snapshot || snapshot.match_state === "drafting" || snapshot.match_state === "game_over") {
    resetMatchInteraction();
    return;
  }

  const localPlayer = snapshot.players.find((player) => player.player_id === snapshot.local_player_id);
  if (!localPlayer?.hand?.length) {
    resetMatchInteraction();
    return;
  }

  const selectedCardId = state.interaction.selectedCardId;
  const selectedStillValid = selectedCardId
    && localPlayer.hand.some((card) => card.id === selectedCardId)
    && !localPlayer.played_card_ids.includes(selectedCardId);

  if (!selectedStillValid) {
    resetMatchInteraction();
    return;
  }

  if (localPlayer.drafted_overload !== null && localPlayer.drafted_overload !== undefined) {
    state.interaction.overloadPreview = Boolean(localPlayer.drafted_overload);
  }
  normalizeSelectionInteraction(localPlayer, selectedCardFor(localPlayer));
  state.interaction.confirmEnabled = localPlayer.player_state === "selecting";
}

function sendMessage(type, payload = {}, overrides = {}) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    showError("WebSocket non connecté.");
    return;
  }

  const envelope = {
    type,
    payload,
    room_id: overrides.room_id ?? state.roomId,
    player_id: overrides.player_id ?? state.playerId,
    timestamp: new Date().toISOString(),
  };

  if (!envelope.room_id) {
    delete envelope.room_id;
  }
  if (!envelope.player_id) {
    delete envelope.player_id;
  }

  state.socket.send(JSON.stringify(envelope));
}

function connectSocket() {
  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    return;
  }

  clearError();
  state.socket = new WebSocket(elements.wsUrl.value);
  elements.connectionStatus.textContent = "Connexion...";

  state.socket.addEventListener("open", () => {
    elements.connectionStatus.textContent = "Connecté";
    elements.createButton.disabled = false;
    elements.joinButton.disabled = false;
    elements.requestStateButton.disabled = false;
    elements.pingButton.disabled = false;
    addLog("Connexion WebSocket ouverte.");

    const savedSession = loadPersistedSession();
    if (savedSession?.roomId && savedSession?.sessionToken) {
      elements.roomId.value = savedSession.roomId;
      elements.playerName.value = savedSession.playerName;
      sendMessage(
        "join_room",
        {
          player_name: savedSession.playerName,
          session_token: savedSession.sessionToken,
        },
        {
          room_id: savedSession.roomId,
          player_id: null,
        },
      );
      addLog(`Tentative de reprise de session pour la room ${savedSession.roomId}.`);
    }
  });

  state.socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    handleServerMessage(message);
  });

  state.socket.addEventListener("close", () => {
    elements.connectionStatus.textContent = "Déconnecté";
    elements.createButton.disabled = true;
    elements.joinButton.disabled = true;
    elements.requestStateButton.disabled = true;
    elements.confirmButton.disabled = true;
    elements.pingButton.disabled = true;
    state.snapshot = null;
    clearRoundResolutionAnimation();
    addLog("Connexion WebSocket fermée.");
    render();
  });
}

function handleServerMessage(message) {
  clearError();

  const { type, payload, room_id: roomId, player_id: playerId } = message;
  if (roomId) {
    state.roomId = roomId;
    elements.roomId.value = roomId;
  }
  if (playerId) {
    state.playerId = playerId;
  }

  switch (type) {
    case "room_created":
      state.sessionToken = payload.session_token;
      persistSession();
      addLog(`Room créée: ${roomId}`);
      break;
    case "room_joined":
      state.sessionToken = payload.session_token;
      persistSession();
      addLog(payload.resumed ? `Session reprise dans ${roomId}.` : `Room rejointe: ${roomId}`);
      break;
    case "player_joined":
      addLog(`${payload.joined_player_name} a rejoint la room.`);
      break;
    case "game_started":
      clearRoundResolutionAnimation();
      state.snapshot = payload.state;
      addLog("La partie commence.");
      break;
    case "state_snapshot":
      if (state.resolution.active) {
        clearRoundResolutionAnimation();
      }
      state.snapshot = payload;
      break;
    case "player_ready":
      state.snapshot = payload.state;
      addLog(`Le joueur ${payload.ready_player_id} a verrouillé son choix.`);
      break;
    case "round_resolved":
      state.snapshot = payload.state;
      startRoundResolutionAnimation(payload.round_result);
      addLog(`Round ${payload.round_result.round_number} résolu.`);
      break;
    case "game_finished":
      state.snapshot = payload.state;
      addLog(payload.winner_id ? `Partie terminée. Gagnant: joueur ${payload.winner_id}.` : "Partie annulée ou sans gagnant.");
      break;
    case "opponent_disconnected":
      clearRoundResolutionAnimation();
      addLog(`${payload.disconnected_player_name} s'est déconnecté.`);
      break;
    case "error":
      showError(payload.message);
      addLog(`Erreur: ${payload.message}`);
      break;
    case "pong":
      addLog("Pong reçu.");
      break;
    default:
      addLog(`Message reçu: ${type}`);
      break;
  }

  syncInteractionWithSnapshot();
  render();
}

function renderPlayers(targetElement) {
  targetElement.innerHTML = "";
  if (!state.snapshot) {
    targetElement.textContent = "Aucun état reçu.";
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "player-list";

  state.snapshot.players.forEach((player) => {
    const row = document.createElement("div");
    row.className = `player-row ${player.player_id === state.snapshot.local_player_id ? "local" : ""}`;

    const title = document.createElement("strong");
    title.textContent = `${player.name} (P${player.player_id})`;
    row.appendChild(title);

    const badges = document.createElement("div");
    badges.className = "badge-row";
    badges.appendChild(makeBadge(`Etat ${player.player_state}`, "state"));
    badges.appendChild(makeBadge(`HP ${player.hit_points ?? "-"}`));
    badges.appendChild(makeBadge(`Pills ${player.pills ?? "-"}`));
    if (player.team_stars !== null && player.team_stars !== undefined) {
      badges.appendChild(makeBadge(`Stars ${player.team_stars}`));
    }
    badges.appendChild(makeBadge(player.ready ? "Verrouillé" : "Libre", player.ready ? "ready" : ""));
    badges.appendChild(makeBadge(player.connected ? "Connecté" : "Déconnecté", player.connected ? "" : "offline"));
    if (player.active_clan_bonuses?.length) {
      badges.appendChild(makeBadge(`Bonus ${player.active_clan_bonuses.join(", ")}`));
    }
    if (player.draft_card_id) {
      badges.appendChild(makeBadge(`Carte ${player.draft_card_id}`));
    }
    if (player.drafted_pills !== null && player.drafted_pills !== undefined) {
      badges.appendChild(makeBadge(`Pills draft ${player.drafted_pills}`));
    }
    if (player.draft_locked) {
      badges.appendChild(makeBadge("Equipe lock", "ready"));
    }

    row.appendChild(badges);
    wrapper.appendChild(row);
  });

  targetElement.appendChild(wrapper);
}

function clanIconFor(clan) {
  const icons = {
    "Pulse 404": "P4",
    Verdelune: "VL",
    "Bastion-9": "B9",
  };
  return icons[clan] ?? clan.slice(0, 2).toUpperCase();
}

function slugifyClan(clan) {
  return clan.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function createClanBadge(clan) {
  const badge = document.createElement("span");
  badge.className = `clan-badge clan-${slugifyClan(clan)}`;

  const icon = document.createElement("span");
  icon.className = "clan-icon";
  icon.textContent = clanIconFor(clan);

  const label = document.createElement("span");
  label.className = "clan-label";
  label.textContent = clan;

  badge.append(icon, label);
  return badge;
}

function createStatChip(label, value) {
  const chip = document.createElement("div");
  chip.className = "card-stat-chip";

  const chipLabel = document.createElement("span");
  chipLabel.className = "card-stat-label";
  chipLabel.textContent = label;

  const chipValue = document.createElement("strong");
  chipValue.className = "card-stat-value";
  chipValue.textContent = value;

  chip.append(chipLabel, chipValue);
  return chip;
}

function createDetailRow(label, value, extraClass = "") {
  const row = document.createElement("div");
  row.className = `card-detail-row ${extraClass}`.trim();

  const heading = document.createElement("span");
  heading.className = "card-detail-label";
  heading.textContent = label;

  const body = document.createElement("span");
  body.className = "card-detail-value";
  body.textContent = value;

  row.append(heading, body);
  return row;
}

function renderTeamSummary(container, options = {}) {
  const {
    title = "Résumé d'équipe",
    cards = [],
    totalStars = 0,
    starCap = null,
    activeBonuses = [],
    teamSize = null,
    emptyText = "Aucune carte sélectionnée.",
  } = options;

  container.innerHTML = "";

  const summary = document.createElement("section");
  summary.className = "team-summary-card";

  const heading = document.createElement("div");
  heading.className = "team-summary-header";

  const titleNode = document.createElement("strong");
  titleNode.textContent = title;
  heading.appendChild(titleNode);

  const meta = document.createElement("div");
  meta.className = "team-summary-chips";
  meta.appendChild(makeBadge(`Cartes ${cards.length}${teamSize ? `/${teamSize}` : ""}`));
  meta.appendChild(makeBadge(`Stars ${totalStars}${starCap ? `/${starCap}` : ""}`));
  meta.appendChild(
    makeBadge(
      activeBonuses.length ? `Bonus actifs ${activeBonuses.join(", ")}` : "Bonus actifs aucun",
      activeBonuses.length ? "ready" : "",
    ),
  );

  const roster = document.createElement("div");
  roster.className = "team-summary-roster";

  if (!cards.length) {
    const empty = document.createElement("div");
    empty.className = "team-summary-empty";
    empty.textContent = emptyText;
    roster.appendChild(empty);
  } else {
    cards.forEach((card) => {
      const item = document.createElement("div");
      item.className = "team-summary-item";
      item.appendChild(createClanBadge(card.clan));

      const name = document.createElement("strong");
      name.textContent = card.name;
      item.appendChild(name);

      const metaText = document.createElement("span");
      metaText.className = "muted";
      metaText.textContent = `${"★".repeat(card.stars)} · POW ${card.power} · DMG ${card.damage}`;
      item.appendChild(metaText);

      const bonusState = document.createElement("span");
      bonusState.className = `team-summary-bonus ${card.bonus_active ? "active" : "inactive"}`;
      bonusState.textContent = card.bonus_active ? "Bonus actif" : "Bonus inactif";
      item.appendChild(bonusState);

      roster.appendChild(item);
    });
  }

  summary.append(heading, meta, roster);
  container.appendChild(summary);
}

function renderDraftOffer(localPlayer) {
  elements.draftOffer.innerHTML = "";
  elements.draftTeam.innerHTML = "";
  elements.draftTeamSummary.innerHTML = "";

  if (!state.snapshot?.draft_offer?.length || !localPlayer) {
    elements.draftStatus.textContent = "En attente de l'offre de draft.";
    elements.draftTeamMeta.textContent = "";
    elements.draftLockButton.textContent = "Verrouiller l'équipe";
    elements.draftLockButton.disabled = true;
    return;
  }

  const selectedIds = new Set((localPlayer.draft_selected_cards ?? []).map((card) => card.id));
  const selectedCards = localPlayer.draft_selected_cards ?? [];
  const activeBonuses = localPlayer.active_clan_bonuses ?? [];
  const starTotal = localPlayer.team_stars ?? 0;
  const lockedLabel = localPlayer.draft_locked ? "Equipe verrouillée côté serveur." : "Compose 4 cartes pour 8 stars max.";
  elements.draftStatus.textContent = `${lockedLabel} Offre commune de ${state.snapshot.draft_offer.length} cartes.`;
  elements.draftTeamMeta.textContent = localPlayer.draft_is_valid
    ? "Composition valide côté serveur."
    : "Sélectionne exactement 4 cartes et reste sous la limite d'étoiles.";
  elements.draftLockButton.textContent = localPlayer.draft_locked ? "Equipe verrouillée" : "Verrouiller l'équipe";
  elements.draftLockButton.disabled = localPlayer.player_state !== "selecting" || localPlayer.draft_locked || !localPlayer.draft_is_valid;

  renderTeamSummary(elements.draftTeamSummary, {
    title: "Equipe sélectionnée",
    cards: selectedCards,
    totalStars: starTotal,
    starCap: state.snapshot.draft_star_cap ?? 8,
    activeBonuses,
    teamSize: state.snapshot.draft_team_size ?? 4,
    emptyText: "Choisis des cartes dans l'offre pour composer ton équipe.",
  });

  state.snapshot.draft_offer.forEach((card) => {
    const isSelected = selectedIds.has(card.id);
    elements.draftOffer.appendChild(
      createCardNode(card, {
        selected: isSelected,
        bonusActive: activeBonuses.includes(card.clan),
        buttonLabel: isSelected ? "Retirer" : "Choisir",
        buttonDisabled: localPlayer.draft_locked || localPlayer.player_state !== "selecting",
        onClick: () => sendMessage("select_card", { card_id: card.id }),
      }),
    );
  });

  selectedCards.forEach((card) => {
    elements.draftTeam.appendChild(createCardNode(card, { selected: true, compact: true }));
  });
}

function selectedCardFor(player) {
  const selectedCardId = player?.player_id === state.snapshot?.local_player_id
    ? state.interaction.selectedCardId
    : player?.draft_card_id;
  if (!selectedCardId) {
    return null;
  }
  return player.hand.find((card) => card.id === selectedCardId) ?? null;
}

function formatClanBonuses(player) {
  if (!player?.active_clan_bonuses?.length) {
    return "Aucun bonus actif";
  }
  return player.active_clan_bonuses.join(", ");
}

function renderIdentityPanel(container, player, roleLabel) {
  container.innerHTML = "";
  if (!player) {
    return;
  }

  const panel = document.createElement("div");
  panel.className = `identity-card ${player.player_id === state.snapshot.local_player_id ? "local" : "opponent"}`;

  const header = document.createElement("div");
  header.className = "identity-top";

  const role = document.createElement("span");
  role.className = "identity-role";
  role.textContent = roleLabel;

  const name = document.createElement("h2");
  name.className = "identity-name";
  name.textContent = player.name;

  header.append(role, name);

  const stats = document.createElement("div");
  stats.className = "identity-stats";
  stats.append(
    createStatChip("HP", player.hit_points ?? "-"),
    createStatChip("Pills", player.pills ?? "-"),
  );

  const meta = document.createElement("div");
  meta.className = "identity-meta";
  meta.append(
    makeBadge(player.ready ? "Choix verrouillé" : "En attente", player.ready ? "ready" : "state"),
    makeBadge(`${player.played_card_ids?.length ?? 0}/4 jouées`),
  );

  const bonusLine = document.createElement("div");
  bonusLine.className = "identity-bonus-line";
  bonusLine.append(
    createClanBadge(player.active_clan_bonuses?.[0] ?? (player.hand?.[0]?.clan ?? "No clan")),
    createDetailRow("Bonus de clan actif", formatClanBonuses(player)),
  );

  panel.append(header, stats, meta, bonusLine);
  container.appendChild(panel);
}

function renderZoneStatus(container, player, { opponent = false } = {}) {
  container.innerHTML = "";
  if (!player) {
    return;
  }

  const selectedCard = selectedCardFor(player);
  const panel = document.createElement("div");
  panel.className = "zone-status-card";

  const title = document.createElement("strong");
  title.className = "zone-status-title";

  const body = document.createElement("div");
  body.className = "zone-status-body";

  if (opponent && !player.ready) {
    title.textContent = "En attente";
    body.textContent = "L'adversaire n'a pas encore verrouillé sa sélection.";
    panel.classList.add("waiting");
  } else if (opponent && selectedCard) {
    title.textContent = "Carte révélée";
    body.textContent = `${selectedCard.name} est visible grâce au flux d'initiative.`;
    panel.classList.add("revealed");
  } else if (player.ready) {
    title.textContent = opponent ? "Carte verrouillée" : "Choix confirmé";
    body.textContent = opponent
      ? "La carte est verrouillée côté serveur. Les pills restent cachées."
      : "Ton choix est confirmé. Attente de la résolution officielle.";
    panel.classList.add(opponent ? "opponent-ready" : "waiting");
  } else {
    title.textContent = "Ton tour";
    body.textContent = "Clique sur une carte puis choisis le nombre de pills.";
    panel.classList.add("your-turn");
  }

  panel.append(title, body);
  container.appendChild(panel);
}

function cardStateLabel({ selected = false, played = false, revealed = false, bonusActive = false, outcome = null }) {
  if (selected) {
    return { tone: "selected", text: "Sélectionnée" };
  }
  if (revealed) {
    return { tone: "revealed", text: "Révélée" };
  }
  if (played) {
    if (outcome === "won") {
      return { tone: "won", text: "Gagné" };
    }
    if (outcome === "lost") {
      return { tone: "lost", text: "Perdu" };
    }
    if (outcome === "tie") {
      return { tone: "tie", text: "Égalité" };
    }
    return { tone: "played", text: "Jouée" };
  }
  return { tone: bonusActive ? "active" : "inactive", text: bonusActive ? "Bonus actif" : "Bonus inactif" };
}

function createCardMedia(card, stateMeta, variant) {
  const media = document.createElement("div");
  media.className = `${variant}-card-media`;

  const image = document.createElement("img");
  image.src = `/${card.illustration}`;
  image.alt = card.name;
  media.appendChild(image);

  const stateBadge = document.createElement("span");
  stateBadge.className = `${variant}-card-badge ${stateMeta.tone}`;
  stateBadge.textContent = stateMeta.text;
  media.appendChild(stateBadge);

  return media;
}

function createCardHeader(card, variant) {
  const header = document.createElement("div");
  header.className = `${variant}-card-header`;

  const titleBlock = document.createElement("div");
  titleBlock.className = `${variant}-card-title-block`;

  const name = document.createElement(variant === "selection" ? "h3" : "strong");
  name.className = `${variant}-card-name`;
  name.textContent = card.name;

  const clanRow = document.createElement("div");
  clanRow.className = `${variant}-card-clan-row`;
  clanRow.appendChild(createClanBadge(card.clan));

  titleBlock.append(name, clanRow);

  const stars = document.createElement("div");
  stars.className = `${variant}-card-stars-wrap`;

  const starCount = document.createElement("span");
  starCount.className = `${variant}-card-stars`;
  starCount.textContent = "★".repeat(card.stars);

  const starLabel = document.createElement("span");
  starLabel.className = `${variant}-card-stars-label`;
  starLabel.textContent = `${card.stars} star${card.stars > 1 ? "s" : ""}`;

  stars.append(starCount, starLabel);
  header.append(titleBlock, stars);
  return header;
}

function createReadableStatChip(label, value, accentClass = "") {
  const chip = document.createElement("div");
  chip.className = `scan-stat-chip ${accentClass}`.trim();

  const chipLabel = document.createElement("span");
  chipLabel.className = "scan-stat-label";
  chipLabel.textContent = label;

  const chipValue = document.createElement("strong");
  chipValue.className = "scan-stat-value";
  chipValue.textContent = value;

  chip.append(chipLabel, chipValue);
  return chip;
}

function createCardStats(card, variant) {
  const stats = document.createElement("div");
  stats.className = `${variant}-card-stats`;
  stats.append(
    createReadableStatChip("Power", card.power, "power"),
    createReadableStatChip("Damage", card.damage, "damage"),
  );
  return stats;
}

function createCardTextGroup(card, variant, bonusActive) {
  const group = document.createElement("div");
  group.className = `${variant}-card-copy`;

  const ability = document.createElement("div");
  ability.className = `${variant}-card-section`;
  ability.append(
    createDetailRow("Ability", card.power_text, `${variant}-ability-row`),
  );

  const bonus = document.createElement("div");
  bonus.className = `${variant}-card-section ${bonusActive ? "bonus-active" : "bonus-inactive"}`;
  bonus.append(
    createDetailRow("Clan bonus", card.bonus_text, `${variant}-bonus-row card-bonus ${bonusActive ? "active" : "inactive"}`),
  );

  const info = card.info
    ? createDetailRow("Info", card.info, `${variant}-info-row`)
    : null;

  const footer = document.createElement("div");
  footer.className = `${variant}-card-footer`;
  footer.append(
    makeBadge(card.clan),
    makeBadge(`${card.stars}★`, "state"),
    makeBadge(bonusActive ? "Bonus actif" : "Bonus inactif", bonusActive ? "ready" : "offline"),
  );

  if (info) {
    group.append(ability, bonus, info, footer);
  } else {
    group.append(ability, bonus, footer);
  }
  return group;
}

function createMatchCardNode(card, options = {}) {
  const {
    selected = false,
    played = false,
    revealed = false,
    localPlayer = false,
    locked = false,
    outcome = null,
    onClick = null,
    disabled = false,
  } = options;
  const bonusActive = card.bonus_active ?? false;
  const stateMeta = cardStateLabel({ selected, played, revealed, bonusActive, outcome });
  const cardNode = document.createElement("article");
  cardNode.className = [
    "match-card",
    localPlayer ? "local-card" : "opponent-card",
    `clan-${slugifyClan(card.clan)}`,
    selected ? "selected" : "",
    played ? "played" : "",
    revealed ? "revealed" : "",
    locked ? "locked" : "",
    outcome ? `outcome-${outcome}` : "",
  ].filter(Boolean).join(" ");

  const sideBadge = document.createElement("span");
  sideBadge.className = `card-side-badge ${localPlayer ? "local" : "opponent"}`;
  sideBadge.textContent = localPlayer ? "TOI" : "ADVERSAIRE";

  const content = document.createElement("div");
  content.className = "match-card-content";
  content.append(
    createCardHeader(card, "match"),
    createCardStats(card, "match"),
    createCardTextGroup(card, "match", bonusActive),
  );
  cardNode.append(sideBadge, createCardMedia(card, stateMeta, "match"), content);

  if (localPlayer) {
    cardNode.classList.add("clickable");
    if (!disabled && onClick) {
      cardNode.addEventListener("click", onClick);
    } else {
      cardNode.classList.add("disabled");
    }
  }

  return cardNode;
}

function playedCardOutcomeFor(player, cardId) {
  if (!player?.played_card_ids?.includes(cardId)) {
    return null;
  }

  const result = (state.snapshot?.history ?? []).find((roundResult) => {
    if (player.player_id === 1) {
      return roundResult.player_1_card_id === cardId;
    }
    if (player.player_id === 2) {
      return roundResult.player_2_card_id === cardId;
    }
    return false;
  });

  if (!result) {
    return null;
  }

  if (result.winner_id === player.player_id) {
    return "won";
  }
  if (result.loser_id === player.player_id) {
    return "lost";
  }
  return "tie";
}

function createSelectionDetailNode(card) {
  const bonusActive = card.bonus_active ?? false;
  const stateMeta = cardStateLabel({ selected: true, bonusActive });
  const detail = document.createElement("div");
  detail.className = `selection-card-detail clan-${slugifyClan(card.clan)}`;

  const content = document.createElement("div");
  content.className = "selection-card-content";
  const bonusStateChip = createReadableStatChip("Bonus", bonusActive ? "Actif" : "Inactif", bonusActive ? "power" : "damage");
  bonusStateChip.classList.add("bonus-state-chip");

  const stats = createCardStats(card, "selection");
  stats.append(bonusStateChip);

  content.append(
    createCardHeader(card, "selection"),
    stats,
    createCardTextGroup(card, "selection", bonusActive),
  );
  detail.append(createCardMedia(card, stateMeta, "selection"), content);
  return detail;
}

function handleLocalCardSelection(localPlayer, card) {
  if (localPlayer.player_state !== "selecting") {
    return;
  }

  if (state.interaction.selectedCardId === card.id) {
    resetMatchInteraction();
    render();
    return;
  }

  const nextPreview = state.interaction.selectedCardId === null
    ? (localPlayer.drafted_pills ?? 0)
    : state.interaction.pillsPreview;
  const nextOverload = state.interaction.selectedCardId === null
    ? Boolean(localPlayer.drafted_overload)
    : state.interaction.overloadPreview;
  state.interaction.selectedCardId = card.id;
  state.interaction.overloadPreview = nextOverload && (localPlayer.pills ?? 0) >= OVERLOAD_PILL_COST;
  state.interaction.pillsPreview = nextPreview;
  normalizeSelectionInteraction(localPlayer, card);
  state.interaction.confirmEnabled = true;
  sendMessage("select_card", { card_id: card.id });
  render();
}

function renderMatchHand(container, player, { localPlayer = false } = {}) {
  container.innerHTML = "";
  if (!player?.hand?.length) {
    return;
  }

  player.hand.slice(0, 4).forEach((card) => {
    const played = player.played_card_ids.includes(card.id);
    const outcome = played ? playedCardOutcomeFor(player, card.id) : null;
    const selected = localPlayer
      ? state.interaction.selectedCardId === card.id || player.draft_card_id === card.id
      : false;
    const revealed = !localPlayer && player.draft_card_id === card.id;
    const locked = player.ready && player.draft_card_id === card.id;
    const canSelect = localPlayer && !played && player.player_state === "selecting";
    container.appendChild(
      createMatchCardNode(card, {
        selected,
        played,
        revealed,
        locked,
        outcome,
        localPlayer,
        disabled: !canSelect,
        onClick: canSelect ? () => handleLocalCardSelection(player, card) : null,
      }),
    );
  });
}

function renderSelectionDetail(localPlayer) {
  elements.selectionDetail.innerHTML = "";

  if (!state.snapshot || state.snapshot.match_state === "drafting") {
    return;
  }

  const card = selectedCardFor(localPlayer);
  if (!card) {
    const empty = document.createElement("div");
    empty.className = "selection-empty-state";
    empty.innerHTML = `
      <strong>Click a card to choose pills.</strong>
      <p>Choisis une carte dans ta main pour afficher son détail complet puis engager tes pills.</p>
    `;
    elements.selectionDetail.appendChild(empty);
    return;
  }

  elements.selectionDetail.appendChild(createSelectionDetailNode(card));
}

function findCardInSnapshot(cardId) {
  for (const player of state.snapshot?.players ?? []) {
    const card = player.hand?.find((candidate) => candidate.id === cardId);
    if (card) {
      return card;
    }
  }
  return {
    id: cardId,
    name: cardId,
    clan: "Inconnu",
    stars: 0,
    power: "-",
    damage: "-",
    power_text: "Carte non trouvée dans le snapshot.",
    bonus_text: "-",
    illustration: "",
    bonus_active: false,
  };
}

function battleStepAtLeast(step) {
  const order = ["idle", "intro", "pills", "attack", "winner", "effects", "done"];
  return order.indexOf(state.resolution.step) >= order.indexOf(step);
}

function createBattleStat(label, value) {
  const stat = document.createElement("div");
  stat.className = "battle-stat";

  const statLabel = document.createElement("span");
  statLabel.textContent = label;

  const statValue = document.createElement("strong");
  statValue.textContent = value;

  stat.append(statLabel, statValue);
  return stat;
}

function createBattleCard(card, options) {
  const { playerLabel, playerId, pills, attack, overload, outcomeClass } = options;
  const cardNode = document.createElement("article");
  cardNode.className = ["battle-card", outcomeClass, `clan-${slugifyClan(card.clan)}`].filter(Boolean).join(" ");

  const heading = document.createElement("div");
  heading.className = "battle-card-heading";

  const player = document.createElement("span");
  player.className = "battle-player-label";
  player.textContent = `${playerLabel} · P${playerId}`;

  const name = document.createElement("h3");
  name.textContent = card.name;

  heading.append(player, name, createClanBadge(card.clan));

  const media = document.createElement("div");
  media.className = "battle-card-media";
  if (card.illustration) {
    const image = document.createElement("img");
    image.src = `/${card.illustration}`;
    image.alt = card.name;
    media.appendChild(image);
  } else {
    const fallback = document.createElement("div");
    fallback.className = "battle-card-fallback";
    fallback.textContent = card.id;
    media.appendChild(fallback);
  }

  const stats = document.createElement("div");
  stats.className = "battle-card-stats";
  stats.append(
    createBattleStat("Puissance", card.power),
    createBattleStat("Dégâts", card.damage),
  );

  if (battleStepAtLeast("pills")) {
    const pillsStat = createBattleStat("Pills d'attaque", pills);
    pillsStat.classList.add("important", "pills-stat", `player-${playerId}`);
    stats.append(pillsStat);

    if (overload) {
      const overloadStat = createBattleStat("Overload", "+2 coût / +3 dégâts si victoire");
      overloadStat.classList.add("overload-stat", `player-${playerId}`);
      stats.append(overloadStat);
    }
  }

  if (battleStepAtLeast("attack")) {
    const attackStat = createBattleStat("Attaque totale", attack);
    attackStat.classList.add("important", "attack-stat");
    stats.append(attackStat);
  }

  const text = document.createElement("div");
  text.className = "battle-card-text";
  text.append(
    createDetailRow("Pouvoir", card.power_text),
    createDetailRow("Bonus", card.bonus_text, `card-bonus ${card.bonus_active ? "active" : "inactive"}`),
  );

  cardNode.append(heading, media, stats, text);
  return cardNode;
}

function battleOutcomeClass(roundResult, playerId) {
  if (!battleStepAtLeast("winner")) {
    return "";
  }
  if (roundResult.winner_id === null || roundResult.winner_id === undefined) {
    return "tie";
  }
  return roundResult.winner_id === playerId ? "winner" : "loser";
}

function buildBattleEffects(roundResult, player1Card, player2Card) {
  const effects = [];
  if (roundResult.winner_id === null || roundResult.winner_id === undefined) {
    effects.push("Égalité : aucun effet de victoire ou défaite.");
  }

  if (roundResult.life_swing_player_1) {
    effects.push(`Joueur 1 vie ${roundResult.life_swing_player_1 > 0 ? "+" : ""}${roundResult.life_swing_player_1}`);
  }
  if (roundResult.life_swing_player_2) {
    effects.push(`Joueur 2 vie ${roundResult.life_swing_player_2 > 0 ? "+" : ""}${roundResult.life_swing_player_2}`);
  }

  const player1PillGain = roundResult.pills_gained_player_1 ?? 0;
  const player2PillGain = roundResult.pills_gained_player_2 ?? 0;
  const stolenByPlayer1 = Math.min(Math.max(player1PillGain, 0), Math.max(-player2PillGain, 0));
  const stolenByPlayer2 = Math.min(Math.max(player2PillGain, 0), Math.max(-player1PillGain, 0));
  if (stolenByPlayer1 > 0) {
    effects.push(`Vol de pill : Joueur 1 vole ${stolenByPlayer1} à Joueur 2`);
  }
  if (stolenByPlayer2 > 0) {
    effects.push(`Vol de pill : Joueur 2 vole ${stolenByPlayer2} à Joueur 1`);
  }

  if (roundResult.pills_gained_player_1) {
    effects.push(`Joueur 1 pills ${roundResult.pills_gained_player_1 > 0 ? "+" : ""}${roundResult.pills_gained_player_1}`);
  }
  if (roundResult.pills_gained_player_2) {
    effects.push(`Joueur 2 pills ${roundResult.pills_gained_player_2 > 0 ? "+" : ""}${roundResult.pills_gained_player_2}`);
  }
  if (roundResult.player_1_overload) {
    effects.push(roundResult.winner_id === 1
      ? `Joueur 1 Overload gagnant : +${roundResult.overload_damage_bonus} dégâts`
      : "Joueur 1 Overload payé : pas de bonus dégâts");
  }
  if (roundResult.player_2_overload) {
    effects.push(roundResult.winner_id === 2
      ? `Joueur 2 Overload gagnant : +${roundResult.overload_damage_bonus} dégâts`
      : "Joueur 2 Overload payé : pas de bonus dégâts");
  }

  const winnerCard = roundResult.winner_id === 1 ? player1Card : roundResult.winner_id === 2 ? player2Card : null;
  if (winnerCard?.power_text?.toLowerCase().includes("poison")) {
    effects.push(`Poison : ${winnerCard.power_text}`);
  }

  if (effects.length === 0) {
    effects.push("Aucun effet additionnel.");
  }

  return effects;
}

function renderBattleResolution(localPlayer, opponent) {
  elements.battleResolution.innerHTML = "";
  const roundResult = state.resolution.roundResult;
  const active = Boolean(state.resolution.active && roundResult);
  const gameOver = state.snapshot?.match_state === "game_over";
  elements.battleResolution.classList.toggle("hidden", !active);
  elements.battleResolution.classList.toggle("active", active);
  ["intro", "pills", "attack", "winner", "effects"].forEach((phase) => {
    elements.battleResolution.classList.toggle(`battle-phase-${phase}`, active && state.resolution.step === phase);
  });
  elements.selectionStage.classList.toggle("hidden", active || gameOver);

  if (!active) {
    return;
  }

  const player1Card = findCardInSnapshot(roundResult.player_1_card_id);
  const player2Card = findCardInSnapshot(roundResult.player_2_card_id);
  const revealOutcome = battleStepAtLeast("winner");
  const localLabel = (playerId) => {
    if (localPlayer?.player_id === playerId) {
      return `Toi · ${localPlayer.name || "Joueur"}`;
    }
    if (opponent?.player_id === playerId) {
      return `Adversaire · ${opponent.name || "Joueur"}`;
    }
    return `Joueur ${playerId}`;
  };

  const phaseCopy = {
    intro: "Les combattants entrent en scène.",
    pills: "Pills d'attaque révélées officiellement. Overload reste séparé du calcul d'attaque.",
    attack: "Attaque totale officielle calculée par le serveur.",
    winner: roundResult.winner_id === null || roundResult.winner_id === undefined
      ? "Égalité : aucune carte ne prend l'avantage."
      : `${localLabel(roundResult.winner_id)} remporte l'affrontement.`,
    effects: "Dégâts et effets appliqués au nouvel état officiel.",
    done: "Résolution terminée.",
  };

  const title = document.createElement("div");
  title.className = "battle-resolution-title";
  const heading = document.createElement("h2");
  heading.textContent = `Résolution du round ${roundResult.round_number}`;
  const subheading = document.createElement("p");
  subheading.className = "muted";
  subheading.textContent = phaseCopy[state.resolution.step] ?? "Résolution en cours.";
  title.append(heading, subheading);

  const board = document.createElement("div");
  board.className = "battle-board";
  board.append(
    createBattleCard(player1Card, {
      playerLabel: localLabel(1),
      playerId: 1,
      pills: roundResult.player_1_pills_committed ?? 0,
      attack: roundResult.player_1_attack,
      overload: Boolean(roundResult.player_1_overload),
      outcomeClass: revealOutcome ? battleOutcomeClass(roundResult, 1) : "",
    }),
  );

  const versus = document.createElement("div");
  versus.className = "battle-versus";
  versus.textContent = "VS";
  board.appendChild(versus);

  board.append(
    createBattleCard(player2Card, {
      playerLabel: localLabel(2),
      playerId: 2,
      pills: roundResult.player_2_pills_committed ?? 0,
      attack: roundResult.player_2_attack,
      overload: Boolean(roundResult.player_2_overload),
      outcomeClass: revealOutcome ? battleOutcomeClass(roundResult, 2) : "",
    }),
  );

  elements.battleResolution.append(title, board);

  if (battleStepAtLeast("winner")) {
    const winnerCall = document.createElement("div");
    winnerCall.className = "battle-winner-call";
    winnerCall.textContent = roundResult.winner_id === null || roundResult.winner_id === undefined
      ? "Égalité"
      : `${localLabel(roundResult.winner_id)} gagne`;
    elements.battleResolution.appendChild(winnerCall);
  }

  if (battleStepAtLeast("effects")) {
    const effects = document.createElement("div");
    effects.className = "battle-effects";
    buildBattleEffects(roundResult, player1Card, player2Card).forEach((effectText) => {
      effects.appendChild(makeBadge(effectText, "state"));
    });
    elements.battleResolution.appendChild(effects);

    const damage = document.createElement("div");
    damage.className = "battle-damage-pop";
    damage.textContent = roundResult.winner_id === null || roundResult.winner_id === undefined
      ? "Dégâts infligés : 0"
      : `Dégâts infligés : ${roundResult.damage_dealt}`;
    elements.battleResolution.appendChild(damage);
  }
}

function renderMatchEndPanel() {
  const snapshot = state.snapshot;
  const visible = Boolean(snapshot?.match_state === "game_over" && !state.resolution.active);
  elements.matchEndPanel.classList.toggle("hidden", !visible);

  if (!visible) {
    return;
  }

  const summary = buildGameOverSummary(snapshot);
  elements.matchEndTitle.textContent = summary.title;
  elements.matchEndReason.textContent = summary.reason;
  elements.matchEndRematchStatus.textContent = summary.rematchStatus;
  elements.rematchButton.disabled = !summary.canRequestRematch;
  elements.rematchButton.textContent = summary.canRequestRematch ? "Rejouer" : "En attente";

  elements.matchEndScore.innerHTML = "";
  summary.scoreLines.forEach((line) => {
    const row = document.createElement("div");
    row.className = `match-end-score-row ${line.isWinner ? "winner" : ""}`.trim();
    row.append(
      makeBadge(line.label, line.isWinner ? "ready" : "state"),
      document.createTextNode(line.name),
      makeBadge(`${line.hp} PV`),
      makeBadge(`${line.pills} pills`),
    );
    elements.matchEndScore.appendChild(row);
  });
}

function updateViewVisibility() {
  const snapshot = state.snapshot;
  const matchState = snapshot?.match_state ?? null;
  const showingResolution = state.resolution.active && state.resolution.roundResult;

  elements.homeView.classList.add("hidden");
  elements.lobbyView.classList.add("hidden");
  elements.gameView.classList.add("hidden");
  elements.endView.classList.add("hidden");

  if (!snapshot) {
    elements.homeView.classList.remove("hidden");
    return;
  }

  if (matchState === "waiting_for_players") {
    elements.lobbyView.classList.remove("hidden");
    return;
  }

  if (matchState === "game_over") {
    elements.gameView.classList.remove("hidden");
    return;
  }

  elements.gameView.classList.remove("hidden");
}

function renderSummary() {
  if (!state.snapshot) {
    elements.summaryContent.textContent = "En attente d'un état de room.";
    elements.lobbyRoomId.textContent = "-";
    elements.lobbyMatchState.textContent = "-";
    elements.roomStatus.textContent = "Aucune room";
    elements.roundValue.textContent = "-";
    elements.initiativeValue.textContent = "-";
    elements.matchStateValue.textContent = "-";
    return;
  }

  const snapshot = state.snapshot;
  const localPlayer = snapshot.players.find((player) => player.player_id === snapshot.local_player_id);
  const selectedCard = selectedCardFor(localPlayer);
  normalizeSelectionInteraction(localPlayer, selectedCard);
  const projection = buildSelectionProjection(localPlayer, selectedCard);
  const initiativeLabel = snapshot.initiative_player_id === snapshot.local_player_id ? "Toi" : "Adversaire";
  elements.roomStatus.textContent = `Room ${state.roomId ?? "-"} | ${snapshot.match_state}`;
  elements.lobbyRoomId.textContent = state.roomId ?? "-";
  elements.lobbyMatchState.textContent = snapshot.match_state;
  elements.roundValue.textContent = snapshot.current_round ?? "-";
  elements.initiativeValue.textContent = snapshot.initiative_player_id ? initiativeLabel : "-";
  elements.matchStateValue.textContent = snapshot.match_state;
  elements.summaryContent.textContent = [
    `Carte sélectionnée : ${projection.selectedName}`,
    `Attaque prévue : ${projection.projectedAttack}`,
    `Dégâts prévus : ${projection.projectedDamage}`,
    `Pills attaque : ${selectedCard ? projection.attackPills : "-"}`,
    `Coût total : ${selectedCard ? formatTotalPillCost(projection) : "-"}`,
    `Overload : ${projection.overloadActive ? "actif" : "inactif"}`,
    `Bonus : ${projection.bonusState}`,
    `Prêts : ${snapshot.pending_player_ids.join(", ") || "aucun"}`,
    snapshot.end_reason ? `Fin: ${snapshot.end_reason}` : null,
  ].filter(Boolean).join(" | ");
}

function renderBanner() {
  const bannerTones = ["your-turn", "waiting", "opponent-ready", "revealed", "resolving"];
  elements.gameBanner.classList.remove(...bannerTones);

  if (!state.snapshot) {
    const status = getTurnStatusMessage(null, null, null);
    elements.gameBanner.textContent = status.text;
    elements.gameBanner.classList.add(status.tone);
    elements.endBanner.textContent = "Partie terminée.";
    elements.endSummary.textContent = "";
    return;
  }

  const snapshot = state.snapshot;
  const localPlayer = snapshot.players.find((player) => player.player_id === snapshot.local_player_id);
  const opponent = snapshot.players.find((player) => player.player_id !== snapshot.local_player_id);
  const status = getTurnStatusMessage(snapshot, localPlayer, opponent);
  elements.gameBanner.textContent = status.text;
  elements.gameBanner.classList.add(status.tone);

  if (snapshot.match_state === "waiting_for_players") {
    return;
  }

  if (snapshot.match_state === "drafting") {
    return;
  }

  if (snapshot.match_state === "round_locked") {
    return;
  }

  if (snapshot.match_state === "round_resolution") {
    return;
  }

  if (snapshot.match_state === "game_over") {
    const summary = buildGameOverSummary(snapshot);
    elements.endBanner.textContent = summary.title;
    elements.endSummary.textContent = summary.reason;
    return;
  }
}

function renderSelection() {
  if (!state.snapshot) {
    elements.selectionInfo.textContent = "Click a card to choose pills.";
    elements.selectionDetail.innerHTML = "";
    elements.selectionControls.classList.add("hidden");
    elements.confirmButton.disabled = true;
    elements.pillsInput.disabled = true;
    elements.overloadInput.disabled = true;
    elements.overloadInput.checked = false;
    elements.overloadMeta.textContent = "";
    return;
  }

  const localPlayer = state.snapshot.players.find((player) => player.player_id === state.snapshot.local_player_id);
  if (!localPlayer) {
    return;
  }

  if (state.snapshot.match_state === "game_over") {
    elements.selectionInfo.textContent = "Partie terminée.";
    elements.selectionDetail.innerHTML = "";
    elements.selectionControls.classList.add("hidden");
    elements.confirmButton.disabled = true;
    elements.pillsInput.disabled = true;
    elements.overloadInput.disabled = true;
    elements.overloadInput.checked = false;
    elements.overloadMeta.textContent = "";
    return;
  }

  if (state.snapshot.match_state === "drafting") {
    elements.confirmButton.textContent = localPlayer.draft_locked ? "Equipe verrouillée" : "Verrouiller l'équipe";
    elements.selectionControls.classList.add("hidden");
    elements.pillsInput.disabled = true;
    elements.overloadInput.disabled = true;
    elements.overloadInput.checked = false;
    elements.overloadMeta.textContent = "";
    elements.confirmButton.disabled = localPlayer.player_state !== "selecting" || localPlayer.draft_locked;
    elements.selectionInfo.textContent = [
      `Equipe ${localPlayer.draft_selected_cards.length}/${state.snapshot.draft_team_size ?? 4}`,
      `Stars ${localPlayer.team_stars ?? 0}/${state.snapshot.draft_star_cap ?? 8}`,
      localPlayer.draft_is_valid ? "Valide" : "Invalide",
    ].join(" | ");
    elements.selectionDetail.innerHTML = "";
    return;
  }

  const selectedCard = selectedCardFor(localPlayer);
  const canAct = localPlayer.player_state === "selecting";
  const showControls = Boolean(selectedCard);
  const canAffordOverload = (localPlayer.pills ?? 0) >= OVERLOAD_PILL_COST;
  normalizeSelectionInteraction(localPlayer, selectedCard);
  const maxPills = maxAttackPillsFor(localPlayer);
  const projection = buildSelectionProjection(localPlayer, selectedCard);

  elements.confirmButton.textContent = "Confirmer";
  elements.pillsInput.max = String(maxPills);
  elements.pillsInput.value = String(state.interaction.pillsPreview);
  elements.pillsValue.textContent = String(state.interaction.pillsPreview);
  elements.overloadInput.checked = state.interaction.overloadPreview;
  elements.overloadInput.disabled = !canAct || !showControls || !canAffordOverload;
  elements.overloadMeta.textContent = showControls
    ? [
      `Pills attaque : ${projection.attackPills}`,
      `Overload : ${projection.overloadActive ? `+${OVERLOAD_PILL_COST}` : "inactif"}`,
      `Coût total : ${formatTotalPillCost(projection)}/${projection.availablePills}`,
      `Attaque prévue : ${projection.projectedAttack}`,
      `Dégâts prévus : ${projection.projectedDamage}`,
    ].join(" | ")
    : "";
  elements.selectionControls.classList.toggle("hidden", !showControls);
  elements.pillsInput.disabled = !canAct || !showControls;
  state.interaction.confirmEnabled = Boolean(showControls && canAct);
  elements.confirmButton.disabled = !state.interaction.confirmEnabled;
  elements.resetSelectionButton.disabled = !showControls;

  elements.selectionInfo.textContent = selectedCard
    ? `${selectedCard.name} · ${selectedCard.clan} · ${selectedCard.bonus_active ? "Bonus actif" : "Bonus inactif"}`
    : "Click a card to choose pills.";
  renderSelectionDetail(localPlayer);
}

function togglePhasePanels() {
  const matchState = state.snapshot?.match_state;
  const drafting = matchState === "drafting";
  const gameOver = matchState === "game_over";

  elements.draftPanel.classList.toggle("hidden", !drafting);
  elements.matchShell.classList.toggle("hidden", drafting);
  elements.selectionStage.classList.toggle("hidden", Boolean(gameOver || state.resolution.active));
  elements.matchEndPanel.classList.toggle("hidden", !gameOver || state.resolution.active);
}

function render() {
  updateViewVisibility();
  togglePhasePanels();
  renderSummary();
  renderBanner();

  if (!state.snapshot) {
    syncMatchSideState(null, null);
    elements.draftOffer.innerHTML = "";
    elements.draftTeam.innerHTML = "";
    elements.draftTeamSummary.innerHTML = "";
    elements.lobbyPlayers.innerHTML = "";
    elements.playerIdentity.innerHTML = "";
    elements.playerStatus.innerHTML = "";
    elements.opponentIdentity.innerHTML = "";
    elements.opponentStatus.innerHTML = "";
    elements.localHand.innerHTML = "";
    elements.opponentHand.innerHTML = "";
    renderBattleResolution(null, null);
    renderSelection();
    return;
  }

  renderPlayers(elements.lobbyPlayers);

  const localPlayer = state.snapshot.players.find((player) => player.player_id === state.snapshot.local_player_id);
  const opponent = state.snapshot.players.find((player) => player.player_id !== state.snapshot.local_player_id);
  syncMatchSideState(localPlayer, opponent);
  renderDraftOffer(localPlayer);
  if (state.snapshot.match_state !== "drafting") {
    renderIdentityPanel(elements.playerIdentity, localPlayer, "Joueur");
    renderIdentityPanel(elements.opponentIdentity, opponent, "Adversaire");
    renderZoneStatus(elements.playerStatus, localPlayer);
    renderZoneStatus(elements.opponentStatus, opponent, { opponent: true });
    renderMatchHand(elements.localHand, localPlayer, { localPlayer: true });
    renderMatchHand(elements.opponentHand, opponent, { localPlayer: false });
  } else {
    syncMatchSideState(null, null);
    elements.playerIdentity.innerHTML = "";
    elements.playerStatus.innerHTML = "";
    elements.opponentIdentity.innerHTML = "";
    elements.opponentStatus.innerHTML = "";
    elements.localHand.innerHTML = "";
    elements.opponentHand.innerHTML = "";
  }
  renderBattleResolution(localPlayer, opponent);
  renderMatchEndPanel();
  renderSelection();
}

function makeBadge(text, extraClass = "") {
  const badge = document.createElement("span");
  badge.className = `badge ${extraClass}`.trim();
  badge.textContent = text;
  return badge;
}

function createCardNode(card, options = {}) {
  const {
    selected = false,
    played = false,
    buttonLabel = null,
    buttonDisabled = true,
    onClick = null,
    compact = false,
    bonusActive = card.bonus_active ?? false,
  } = options;
  const cardNode = document.createElement("article");
  cardNode.className = `card ${selected ? "selected" : ""} ${played ? "played" : ""} ${compact ? "compact-card" : ""}`.trim();

  const media = document.createElement("div");
  media.className = "card-media";

  const image = document.createElement("img");
  image.src = `/${card.illustration}`;
  image.alt = card.name;
  media.appendChild(image);

  const bonusState = document.createElement("span");
  bonusState.className = `card-bonus-state ${bonusActive ? "active" : "inactive"}`;
  bonusState.textContent = bonusActive ? "Bonus actif" : "Bonus inactif";
  media.appendChild(bonusState);
  cardNode.appendChild(media);

  const title = document.createElement("div");
  title.className = "card-title-row";

  const titleStack = document.createElement("div");
  titleStack.className = "card-title-stack";

  const name = document.createElement("strong");
  name.className = "card-name";
  name.textContent = card.name;
  titleStack.appendChild(name);
  titleStack.appendChild(createClanBadge(card.clan));

  const stars = document.createElement("span");
  stars.className = "card-stars";
  stars.textContent = "★".repeat(card.stars);

  title.append(titleStack, stars);
  cardNode.appendChild(title);

  const stats = document.createElement("div");
  stats.className = "card-stat-row";
  stats.append(
    createStatChip("Power", card.power),
    createStatChip("Damage", card.damage),
  );
  cardNode.appendChild(stats);

  const details = document.createElement("div");
  details.className = "card-details";
  details.append(
    createDetailRow("Pouvoir", card.power_text),
    createDetailRow("Bonus clan", card.bonus_text, `card-bonus ${bonusActive ? "active" : "inactive"}`),
  );
  cardNode.appendChild(details);

  const footer = document.createElement("div");
  footer.className = "card-footer-row";
  footer.append(
    makeBadge(card.clan),
    makeBadge(`${card.stars}★`),
    makeBadge(bonusActive ? "Actif" : "Inactif", bonusActive ? "ready" : "offline"),
  );
  cardNode.appendChild(footer);

  if (buttonLabel) {
    const button = document.createElement("button");
    button.className = "card-action-button";
    button.textContent = buttonLabel;
    button.disabled = buttonDisabled;
    if (onClick) {
      button.addEventListener("click", onClick);
    }
    cardNode.appendChild(button);
  }

  return cardNode;
}

elements.connectButton.addEventListener("click", connectSocket);
elements.createButton.addEventListener("click", () => {
  clearPersistedSession();
  sendMessage("create_room", { player_name: elements.playerName.value }, { room_id: null, player_id: null });
});
elements.joinButton.addEventListener("click", () => {
  const savedSession = loadPersistedSession();
  const payload = { player_name: elements.playerName.value };
  if (savedSession?.roomId === elements.roomId.value && savedSession?.sessionToken) {
    payload.session_token = savedSession.sessionToken;
  }
  sendMessage("join_room", payload, { room_id: elements.roomId.value, player_id: null });
});
elements.requestStateButton.addEventListener("click", () => sendMessage("request_state", {}));
elements.confirmButton.addEventListener("click", () => sendMessage("confirm_selection", {}));
elements.draftLockButton.addEventListener("click", () => sendMessage("confirm_selection", {}));
elements.pingButton.addEventListener("click", () => sendMessage("ping", { nonce: crypto.randomUUID() }));
elements.resetSelectionButton.addEventListener("click", () => {
  resetMatchInteraction();
  render();
});
elements.returnHomeButton.addEventListener("click", () => {
  state.snapshot = null;
  resetMatchInteraction();
  clearRoundResolutionAnimation();
  clearPersistedSession();
  render();
});
elements.returnHomeButtonInline.addEventListener("click", () => {
  state.snapshot = null;
  resetMatchInteraction();
  clearRoundResolutionAnimation();
  clearPersistedSession();
  render();
});
elements.rematchButton.addEventListener("click", () => {
  sendMessage("request_rematch", {});
});
elements.pillsInput.addEventListener("input", (event) => {
  if (!state.interaction.selectedCardId) {
    return;
  }
  const localPlayer = state.snapshot?.players.find((player) => player.player_id === state.snapshot.local_player_id);
  const rawPills = Number(event.target.value);
  const pills = Math.max(0, Math.min(maxAttackPillsFor(localPlayer), Number.isFinite(rawPills) ? rawPills : 0));
  state.interaction.pillsPreview = pills;
  event.target.value = String(pills);
  elements.pillsValue.textContent = String(pills);
  sendMessage("set_pills", { pills });
  render();
});
elements.overloadInput.addEventListener("change", (event) => {
  if (!state.interaction.selectedCardId) {
    event.target.checked = false;
    return;
  }
  const localPlayer = state.snapshot?.players.find((player) => player.player_id === state.snapshot.local_player_id);
  const selectedCard = selectedCardFor(localPlayer);
  const canUseOverload = Boolean(selectedCard) && (localPlayer?.pills ?? 0) >= OVERLOAD_PILL_COST;
  state.interaction.overloadPreview = Boolean(event.target.checked) && canUseOverload;
  const beforeClamp = state.interaction.pillsPreview;
  normalizeSelectionInteraction(localPlayer, selectedCard);
  event.target.checked = state.interaction.overloadPreview;
  if (state.interaction.pillsPreview !== beforeClamp) {
    sendMessage("set_pills", { pills: state.interaction.pillsPreview });
  }
  sendMessage("set_overload", { overload: state.interaction.overloadPreview });
  render();
});

const savedSession = loadPersistedSession();
elements.wsUrl.value = buildDefaultWebSocketUrl();
if (savedSession) {
  elements.roomId.value = savedSession.roomId ?? "";
  elements.playerName.value = savedSession.playerName ?? "Player";
}

ensureMatchSideChrome();
render();
