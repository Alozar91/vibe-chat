/**
 * Оверлей звонка (§3.12): входящий/исходящий ринг + панель активного звонка.
 * Состояние — calls-стор (Zustand); компонент монтируется у корня (app)/_layout,
 * поэтому звонок не рвётся при навигации (как в вебе, §17).
 *
 * Рисуется в отдельном окне (Modal): sibling-View поверх native-stack
 * (react-native-screens) не гарантирует z-порядок — панель звонка получала
 * нативный узел с корректными bounds, но оставалась за содержимым экрана.
 *
 * Этап 9 (аудио): ринг-карточка direct, баннер чужого group-звонка,
 * панель активного аудио (таймер, mute, динамик, hang-up, состав).
 * Этап 10 (видео): полноэкранный оверлей — remote на весь экран + PiP себя
 * (direct) или грид плиток (group), кнопки камера/микрофон/динамик/сброс;
 * keep-awake на время звонка. Ринг-карточка проверяется РАНЬШЕ видео-ветки
 * (иначе перекрывала «Ответить/Отклонить» — тот же баг, что в вебе §17).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal, Pressable, StyleSheet, Text, Vibration, View } from "react-native";
import { VideoView } from "@livekit/react-native";
import type { VideoTrack } from "livekit-client";
import { activateKeepAwakeAsync, deactivateKeepAwake } from "expo-keep-awake";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { chatsApi } from "../api/endpoints";
import { queryKeys } from "../api/query-keys";
import { t } from "../i18n/ru";
import { useCalls } from "../stores/calls";
import { useSession } from "../stores/session";
import { theme } from "../theme";

/** Тик раз в секунду для таймера звонка. */
function useTick(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

function fmtDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Короткая вибрация-подтверждение при смене статуса звонка (accept/ended). */
function buzz(): void {
  Vibration.vibrate(60);
}

export function CallOverlay() {
  const call = useCalls((s) => s.current);
  const media = useCalls((s) => s.media);
  const muted = useCalls((s) => s.muted);
  const speakerOn = useCalls((s) => s.speakerOn);
  const camOn = useCalls((s) => s.camOn);
  const remoteCams = useCalls((s) => s.remoteCams);
  const localCam = useCalls((s) => s.localCam);
  const error = useCalls((s) => s.error);
  const accept = useCalls((s) => s.accept);
  const reject = useCalls((s) => s.reject);
  const cancel = useCalls((s) => s.cancel);
  const join = useCalls((s) => s.join);
  const leave = useCalls((s) => s.leave);
  const toggleMute = useCalls((s) => s.toggleMute);
  const toggleCam = useCalls((s) => s.toggleCam);
  const toggleSpeaker = useCalls((s) => s.toggleSpeaker);
  const myId = useSession((s) => s.user?.id ?? "");

  const tick = useTick();
  const insets = useSafeAreaInsets();
  // §3.12: detail нужен только когда есть звонок; иначе (enabled=false) запрос
  // не фетчится — useChatDetail("") попадал бы в GET /chats/ (список)
  const detail = useQuery({
    // ключ без call.chat_id не должен пересекаться с кэшем списков (§3.4:
    // persist в MMKV; баг-кей «useChatDetail("") → массив чатов»);
    queryKey: queryKeys.chats.detail(call?.chat_id ?? "inactive"),
    queryFn: () => chatsApi.get(call!.chat_id),
    enabled: !!call,
  });

  // названия: direct — имя собеседника; group — название группы (§17 UI);
  // guard по форме: в MMKV-кэше может лежать мусор из старой сборки
  const peerLabel = useMemo(() => {
    const d = detail.data;
    if (!d || Array.isArray(d) || !("members" in d)) return "…";
    if (d.type === "group") return d.title ?? "…";
    const peer = d.members.find((m) => m.user_id !== myId)?.user;
    return peer?.display_name ?? "…";
  }, [detail.data, myId]);

  const memberNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of detail.data?.members ?? []) map.set(m.user_id, m.user.display_name);
    return map;
  }, [detail.data]);

  // вибро-отклик на смену статуса звонка (accepted → активный; ended → сброс)
  const prevStatus = useRef<string | null>(null);
  useEffect(() => {
    const status = call?.status ?? null;
    if (prevStatus.current && status && prevStatus.current !== status) buzz();
    prevStatus.current = status;
  }, [call?.status]);

  // экран не гаснет во время звонка (§3.12 — обязательно для видео)
  const hasCall = !!call;
  useEffect(() => {
    if (!hasCall) return;
    let mounted = true;
    void activateKeepAwakeAsync().catch(() => {});
    return () => {
      if (mounted) {
        mounted = false;
        deactivateKeepAwake();
      }
    };
  }, [hasCall]);

  if (!call && !error) return null;

  const isGroup = detail.data?.type === "group";
  const isVideo = call?.kind === "video";
  const iAmIn = call?.participant_ids.includes(myId) ?? false;
  const isRinging = call?.status === "ringing";
  const durationStart = call?.started_at ? new Date(call.started_at).getTime() : null;
  const duration = durationStart ? Math.max(0, Math.floor((tick - durationStart) / 1000)) : 0;
  const memberList = call?.participant_ids.map((id) => memberNames.get(id) ?? id.slice(0, 8)) ?? [];

  return (
    <Modal
      visible={!!call || !!error}
      transparent
      statusBarTranslucent
      animationType="none"
      onRequestClose={() => {}}
    >
      {/* ринг — полноэкранный скрим (блокирует); активный звонок — только
          панель (box-none), чтобы можно было пользоваться чатами во время разговора */}
      <View style={styles.overlayRoot} pointerEvents={isRinging ? "auto" : "box-none"}>
        {error ? (
          <View style={[styles.errorToast, { bottom: insets.bottom + (call ? 80 : 60) }]} pointerEvents="none">
            <Text style={styles.errorText}>{t(`call.${error}` as never)}</Text>
          </View>
        ) : null}
        {!call ? null : isGroup && !iAmIn && call.status !== "ended" ? (
          <View style={[styles.groupBanner, { bottom: insets.bottom + 16 }]} pointerEvents="box-none">
            <Text style={styles.groupBannerText} numberOfLines={1}>
              👥 {peerLabel} · {t(isVideo ? "call.joinVideoBanner" : "call.joinBanner", { n: call.participant_ids.length })}
            </Text>
            <Pressable style={styles.joinBtn} onPress={() => void join(call.id)}>
              <Text style={styles.joinBtnText}>{t("call.join")}</Text>
            </Pressable>
          </View>
        ) : isRinging ? (
          <RingCard
            peerLabel={peerLabel}
            isInitiator={call.initiator_id === myId}
            isVideo={isVideo}
            error={error}
            accept={() => void accept()}
            reject={() => void reject()}
            cancel={() => void cancel()}
          />
        ) : isVideo ? (
          <ActiveVideo
            peerLabel={peerLabel}
            isGroup={isGroup}
            myId={myId}
            memberNames={memberNames}
            media={media}
            muted={muted}
            camOn={camOn}
            speakerOn={speakerOn}
            remoteCams={remoteCams}
            localCam={localCam}
            duration={duration}
            insetsTop={insets.top}
            insetsBottom={insets.bottom}
            toggleMute={() => void toggleMute()}
            toggleCam={() => void toggleCam()}
            toggleSpeaker={() => void toggleSpeaker()}
            leave={() => void leave()}
          />
        ) : (
          <ActivePanel
            peerLabel={peerLabel}
            isGroup={isGroup}
            memberList={memberList}
            media={media}
            muted={muted}
            speakerOn={speakerOn}
            duration={duration}
            insetsBottom={insets.bottom}
            toggleMute={() => void toggleMute()}
            toggleSpeaker={() => void toggleSpeaker()}
            leave={() => void leave()}
          />
        )}
      </View>
    </Modal>
  );
}

/** Ринг (direct): карточка «Ответить/Отклонить» (у инициатора — «Отменить»). */
function RingCard(props: {
  peerLabel: string;
  isInitiator: boolean;
  isVideo: boolean;
  error: string | null;
  accept: () => void;
  reject: () => void;
  cancel: () => void;
}) {
  return (
    <View style={styles.ringBackdrop} pointerEvents="auto">
      <View style={styles.ringCard}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{props.peerLabel.slice(0, 2).toUpperCase()}</Text>
        </View>
        <Text style={styles.ringName}>{props.peerLabel}</Text>
        <Text style={styles.ringStatus}>
          {props.isInitiator
            ? t(props.isVideo ? "call.outgoingVideo" : "call.outgoingAudio")
            : t(props.isVideo ? "call.incomingVideo" : "call.incomingAudio")}
        </Text>
        <View style={styles.ringButtons}>
          {props.isInitiator ? (
            <Pressable style={[styles.circleBtn, styles.danger]} onPress={props.cancel}>
              <Text style={styles.circleBtnText}>✕</Text>
            </Pressable>
          ) : (
            <>
              <Pressable style={[styles.circleBtn, styles.danger]} onPress={props.reject}>
                <Text style={styles.circleBtnText}>✕</Text>
              </Pressable>
              <Pressable style={[styles.circleBtn, styles.ok]} onPress={props.accept}>
                <Text style={styles.circleBtnText}>📞</Text>
              </Pressable>
            </>
          )}
        </View>
      </View>
      {props.error ? (
        <View style={styles.errorToastInline} pointerEvents="none">
          <Text style={styles.errorText}>{t(`call.${props.error}` as never)}</Text>
        </View>
      ) : null}
    </View>
  );
}

/** Живая плитка видео или заглушка с аватаром. */
function VideoTile(props: {
  name: string;
  track: VideoTrack | null;
  mirror: boolean;
  zOrder: number;
  style?: object;
  isSelf?: boolean;
}) {
  if (props.track) {
    return (
      <View style={[styles.tile, props.style]}>
        <VideoView
          videoTrack={props.track}
          style={{ ...StyleSheet.absoluteFillObject }}
          objectFit="cover"
          mirror={props.mirror}
          zOrder={props.zOrder}
        />
        <View style={styles.tileLabelWrap} pointerEvents="none">
          <Text style={styles.tileLabel} numberOfLines={1}>
            {props.name}
          </Text>
        </View>
      </View>
    );
  }
  return (
    <View style={[styles.tile, styles.tileAvatarBg, props.style]}>
      <View style={styles.tileAvatar}>
        <Text style={styles.avatarText}>{props.name.slice(0, 2).toUpperCase()}</Text>
      </View>
      <View style={styles.tileLabelWrap} pointerEvents="none">
        <Text style={styles.tileLabel} numberOfLines={1}>
          {props.name}
        </Text>
      </View>
    </View>
  );
}

/**
 * Активный видео-звонок (этап 10): полноэкранный оверлей.
 * direct — собеседник на весь экран + PiP себя справа сверху;
 * group — грид плиток до 8 камер (2×N, §17), своя плитка первая.
 * При отсутствии живых камер — заглушки с аватарами + подпись «Видео выключено».
 */
function ActiveVideo(props: {
  peerLabel: string;
  isGroup: boolean;
  myId: string;
  memberNames: Map<string, string>;
  media: string;
  muted: boolean;
  camOn: boolean;
  speakerOn: boolean;
  remoteCams: Record<string, VideoTrack | null>;
  localCam: VideoTrack | null;
  duration: number;
  insetsTop: number;
  insetsBottom: number;
  toggleMute: () => void;
  toggleCam: () => void;
  toggleSpeaker: () => void;
  leave: () => void;
}) {
  // плитки: своя первая, потом участники с participant_ids (как в аудио-панели)
  const tiles = useMemo(() => {
    const list: { id: string; name: string; track: VideoTrack | null; self: boolean }[] = [
      { id: props.myId, name: t("call.me"), track: props.localCam, self: true },
    ];
    for (const [id, track] of Object.entries(props.remoteCams)) {
      if (id === props.myId) continue;
      list.push({ id, name: props.memberNames.get(id) ?? id.slice(0, 8), track, self: false });
    }
    return list.slice(0, 8); // до 8 камер (§17)
  }, [props.myId, props.localCam, props.remoteCams, props.memberNames]);

  const anyVideo = tiles.some((x) => x.track);
  const rows = Math.max(1, Math.ceil(tiles.length / 2));
  const connected = props.media === "connected";

  if (!props.isGroup) {
    // 1:1: собеседник на весь экран, себя — PiP справа сверху
    const peerTile = tiles.find((x) => !x.self);
    return (
      <View style={styles.videoRoot}>
        <VideoTile
          name={props.peerLabel}
          track={peerTile?.track ?? null}
          mirror={false}
          zOrder={0}
          style={styles.videoFullscreen}
        />
        {!anyVideo ? <Text style={styles.videoOffHint}>{t("call.videoOffAll")}</Text> : null}
        {props.localCam ? (
          <View style={[styles.pip, { top: props.insetsTop + 52, right: theme.spacing.lg }]}>
            <VideoView
              videoTrack={props.localCam}
              style={{ ...StyleSheet.absoluteFillObject }}
              objectFit="cover"
              mirror
            />
          </View>
        ) : null}
        <VideoHeader
          peerLabel={props.peerLabel}
          media={props.media}
          duration={props.duration}
          insetsTop={props.insetsTop}
        />
        <VideoControls
          insetsBottom={props.insetsBottom}
          muted={props.muted}
          camOn={props.camOn}
          speakerOn={props.speakerOn}
          connected={connected}
          toggleMute={props.toggleMute}
          toggleCam={props.toggleCam}
          toggleSpeaker={props.toggleSpeaker}
          leave={props.leave}
        />
      </View>
    );
  }

  return (
    <View style={styles.videoRoot}>
      <View style={styles.gridWrap}>
        {tiles.map((x) => (
          <VideoTile
            key={x.id}
            name={x.name}
            track={x.track}
            mirror={x.self}
            zOrder={x.self ? 1 : 0}
            style={{ width: "50%", height: `${100 / rows}%` }}
          />
        ))}
      </View>
      {!anyVideo ? <Text style={styles.videoOffHint}>{t("call.videoOffAll")}</Text> : null}
      <VideoHeader
        peerLabel={props.peerLabel}
        media={props.media}
        duration={props.duration}
        insetsTop={props.insetsTop}
      />
      <VideoControls
        insetsBottom={props.insetsBottom}
        muted={props.muted}
        camOn={props.camOn}
        speakerOn={props.speakerOn}
        connected={connected}
        toggleMute={props.toggleMute}
        toggleCam={props.toggleCam}
        toggleSpeaker={props.toggleSpeaker}
        leave={props.leave}
      />
    </View>
  );
}

/** Шапка поверх видео: имя, статус-точка, таймер. */
function VideoHeader(props: { peerLabel: string; media: string; duration: number; insetsTop: number }) {
  return (
    <View style={[styles.videoHeader, { top: props.insetsTop + 8 }]} pointerEvents="none">
      <View style={[styles.statusDot, { backgroundColor: props.media === "connected" ? theme.colors.accentGreen : "#eab308" }]} />
      <Text style={styles.videoName} numberOfLines={1}>
        {props.peerLabel}
      </Text>
      <Text style={styles.videoTimer}>
        {props.media === "connected" ? fmtDuration(props.duration) : t("call.connecting")}
      </Text>
    </View>
  );
}

/** Кнопки поверх видео: микрофон / камера / динамик / сброс. */
function VideoControls(props: {
  insetsBottom: number;
  muted: boolean;
  camOn: boolean;
  speakerOn: boolean;
  connected: boolean;
  toggleMute: () => void;
  toggleCam: () => void;
  toggleSpeaker: () => void;
  leave: () => void;
}) {
  return (
    <View style={[styles.videoControls, { bottom: props.insetsBottom + 24 }]}>
      <Pressable
        style={[styles.videoBtn, props.muted && styles.dangerOn]}
        onPress={props.toggleMute}
        disabled={!props.connected}
      >
        <Text style={styles.videoBtnText}>{props.muted ? "🔇" : "🎙"}</Text>
      </Pressable>
      <Pressable
        style={[styles.videoBtn, !props.camOn && styles.dangerOn]}
        onPress={props.toggleCam}
        disabled={!props.connected}
      >
        <Text style={styles.videoBtnText}>{props.camOn ? "🎥" : "🚫"}</Text>
      </Pressable>
      <Pressable
        style={[styles.videoBtn, props.speakerOn && styles.okOn]}
        onPress={props.toggleSpeaker}
        disabled={!props.connected}
      >
        <Text style={styles.videoBtnText}>🔈</Text>
      </Pressable>
      <Pressable style={[styles.videoBtn, styles.danger]} onPress={props.leave} accessibilityLabel={t("call.hangup")}>
        <Text style={styles.videoBtnText}>📵</Text>
      </Pressable>
    </View>
  );
}

/** Активный аудио-звонок: панель снизу (direct — компакт; group — с составом). */
function ActivePanel(props: {
  peerLabel: string;
  isGroup: boolean;
  memberList: string[];
  media: string;
  muted: boolean;
  speakerOn: boolean;
  duration: number;
  insetsBottom: number;
  toggleMute: () => void;
  toggleSpeaker: () => void;
  leave: () => void;
}) {
  return (
    <View style={[styles.activePanel, { bottom: props.insetsBottom + 16 }]} pointerEvents="box-none">
      <View
        style={[
          styles.statusDot,
          { backgroundColor: props.media === "connected" ? theme.colors.accentGreen : "#eab308" },
        ]}
      />
      <Text style={styles.activeName} numberOfLines={1}>
        {props.peerLabel}
      </Text>
      {props.isGroup ? (
        <Text style={styles.activeMembers} numberOfLines={1}>
          {t("call.members", { n: props.memberList.length, names: props.memberList.join(", ") })}
        </Text>
      ) : null}
      <Text style={styles.activeTimer}>
        {props.media === "connected" ? fmtDuration(props.duration) : t("call.connecting")}
      </Text>
      <View style={styles.controlsRow}>
        <Pressable style={[styles.smallBtn, props.muted && styles.dangerOn]} onPress={props.toggleMute} disabled={props.media !== "connected"}>
          <Text style={styles.smallBtnText}>{props.muted ? "🔇" : "🎙"}</Text>
        </Pressable>
        <Pressable style={[styles.smallBtn, props.speakerOn && styles.okOn]} onPress={props.toggleSpeaker} disabled={props.media !== "connected"}>
          <Text style={styles.smallBtnText}>🔈</Text>
        </Pressable>
        <Pressable
          style={[styles.smallBtn, styles.danger]}
          onPress={props.leave}
          accessibilityLabel={props.isGroup ? t("call.leave") : t("call.hangup")}
        >
          <Text style={styles.smallBtnText}>📵</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  overlayRoot: { flex: 1 },
  ringBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 100,
  },
  ringCard: {
    width: 300,
    borderRadius: theme.radius.lg,
    backgroundColor: theme.colors.background,
    padding: theme.spacing.xl,
    alignItems: "center",
    gap: theme.spacing.md,
    shadowColor: "#000",
    shadowOpacity: 0.25,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 8 },
    elevation: 12,
  },
  avatar: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: theme.colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { color: theme.colors.primaryText, fontSize: 22, fontWeight: "700" },
  ringName: { color: theme.colors.text, fontSize: theme.font.lg, fontWeight: "600" },
  ringStatus: { color: theme.colors.textSecondary, fontSize: theme.font.md },
  ringButtons: { flexDirection: "row", gap: theme.spacing.xl, marginTop: theme.spacing.md },
  circleBtn: {
    width: 60,
    height: 60,
    borderRadius: 30,
    alignItems: "center",
    justifyContent: "center",
  },
  circleBtnText: { color: "#fff", fontSize: 22 },
  danger: { backgroundColor: theme.colors.danger },
  ok: { backgroundColor: theme.colors.accentGreen },
  groupBanner: {
    position: "absolute",
    left: theme.spacing.lg,
    right: theme.spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    gap: theme.spacing.md,
    backgroundColor: theme.colors.background,
    borderRadius: theme.radius.full,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    shadowColor: "#000",
    shadowOpacity: 0.15,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 8,
    zIndex: 100,
  },
  groupBannerText: { flex: 1, color: theme.colors.text, fontSize: theme.font.md, fontWeight: "500" },
  joinBtn: {
    backgroundColor: theme.colors.accentGreen,
    borderRadius: theme.radius.full,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 8,
  },
  joinBtnText: { color: "#fff", fontSize: theme.font.sm, fontWeight: "600" },
  activePanel: {
    position: "absolute",
    left: theme.spacing.lg,
    right: theme.spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: theme.spacing.sm,
    backgroundColor: theme.colors.background,
    borderRadius: theme.radius.full,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    shadowColor: "#000",
    shadowOpacity: 0.15,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 8,
    zIndex: 100,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  activeName: { color: theme.colors.text, fontSize: theme.font.md, fontWeight: "600", maxWidth: 120 },
  activeMembers: { color: theme.colors.textSecondary, fontSize: theme.font.sm, flexShrink: 1, flexGrow: 1 },
  activeTimer: { color: theme.colors.textSecondary, fontSize: theme.font.sm },
  controlsRow: { flexDirection: "row", gap: theme.spacing.sm, marginLeft: "auto" },
  smallBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: theme.colors.surface,
    alignItems: "center",
    justifyContent: "center",
    opacity: 1,
  },
  smallBtnText: { fontSize: 17 },
  dangerOn: { backgroundColor: theme.colors.danger },
  okOn: { backgroundColor: theme.colors.accentGreen },
  // --- видео (этап 10) ---
  videoRoot: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "#000",
    zIndex: 50,
  },
  videoFullscreen: { ...StyleSheet.absoluteFillObject },
  pip: {
    position: "absolute",
    width: 110,
    height: 165,
    borderRadius: theme.radius.md,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.35)",
    elevation: 6,
  },
  videoHeader: {
    position: "absolute",
    left: theme.spacing.xl,
    right: theme.spacing.xl,
    flexDirection: "row",
    alignItems: "center",
    gap: theme.spacing.sm,
    backgroundColor: "rgba(0,0,0,0.45)",
    borderRadius: theme.radius.full,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.sm,
    alignSelf: "flex-start",
    minWidth: 220,
  },
  videoName: { color: "#fff", fontSize: theme.font.md, fontWeight: "600", flexShrink: 1 },
  videoTimer: { color: "rgba(255,255,255,0.8)", fontSize: theme.font.sm },
  videoControls: {
    position: "absolute",
    left: 0,
    right: 0,
    flexDirection: "row",
    justifyContent: "center",
    gap: theme.spacing.xl,
  },
  videoBtn: {
    width: 62,
    height: 62,
    borderRadius: 31,
    backgroundColor: "rgba(30,30,30,0.65)",
    alignItems: "center",
    justifyContent: "center",
  },
  videoBtnText: { fontSize: 24 },
  gridWrap: {
    ...StyleSheet.absoluteFillObject,
    flexDirection: "row",
    flexWrap: "wrap",
    paddingTop: 96,
  },
  tile: { overflow: "hidden", backgroundColor: "#111" },
  tileAvatarBg: { alignItems: "center", justifyContent: "center" },
  tileAvatar: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: theme.colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  tileLabelWrap: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.45)",
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 4,
  },
  tileLabel: { color: "#fff", fontSize: theme.font.sm },
  videoOffHint: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 120,
    textAlign: "center",
    color: "rgba(255,255,255,0.75)",
    fontSize: theme.font.sm,
  },
  errorToast: {
    position: "absolute",
    left: theme.spacing.xl,
    right: theme.spacing.xl,
    backgroundColor: theme.colors.danger,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    zIndex: 110,
  },
  errorToastInline: {
    position: "absolute",
    bottom: 12,
    backgroundColor: theme.colors.danger,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
  },
  errorText: { color: "#fff", fontSize: theme.font.sm, textAlign: "center" },
});
