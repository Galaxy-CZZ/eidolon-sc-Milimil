"use client";

import { notFound, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { BarCounter, useBarCounter } from "@/components/play/bar/BarCounter";
import { BarDoor } from "@/components/play/bar/BarDoor";
import { BarEndCard } from "@/components/play/bar/BarEndCard";
import { BarGuest } from "@/components/play/bar/BarGuest";
import { BarJukeboxPlayer, BarJukeboxSetup } from "@/components/play/bar/BarJukebox";
import { BarRecipeBook } from "@/components/play/bar/BarRecipeBook";
import { BarRoom } from "@/components/play/bar/BarRoom";
import { BarScreen, jukeboxCell, SideMenu } from "@/components/play/bar/BarScreen";
import { BarSettingsBox } from "@/components/play/bar/BarSettingsBox";
import { BarTextBox } from "@/components/play/bar/BarTextBox";
import { BAR_INK } from "@/components/play/bar/ink";
import { PortraitGuard } from "@/components/play/bar/PortraitGuard";
import { useBarFullscreen } from "@/components/play/bar/useBarFullscreen";
import { canSetMusicVolume, useBarJukebox } from "@/components/play/bar/useBarJukebox";
import { useBarSettings } from "@/components/play/bar/useBarSettings";
import { useBarSound } from "@/components/play/bar/useBarSound";
import { useBarVoice } from "@/components/play/bar/useBarVoice";
import { useBarTutorial } from "@/components/play/bar/useBarTutorial";
import { useBarVisit } from "@/components/play/bar/useBarVisit";
import { useBar } from "@/components/play/useBar";
import { copy } from "@/i18n";
import { gainOf } from "@/lib/barSettings";
import type { TutorialEnd } from "@/lib/barTutorial";
import { isArrowShown, isCounterOpen, isSpeaking, mixingMemo, shownText, typingVoice } from "@/lib/barScene";
import { endCard } from "@/lib/barVisit";
import { getGiftState } from "@/lib/gifts";
import { playHref } from "@/lib/playRoute";

/** 句子打字时循环的打字音效。 */
const TYPING_SOUND = { her: "bleep_high", producer: "bleep_low" } as const;

/**
 * 酒吧（`/play/bar`，.scratch/bar-room spec「入口、路由和外壳」「一次营业的流程」）：在导航外壳里（通话不挂断，ADR-0018），
 * 画面盖住导航栏和 dock，正在通话时通话条照旧在最上面。先读 `GET /api/bar`：读到关着时当作没有这一页（not-found）；
 * 读到之前只有一层底色；读不到时照样画画面，「离开」能用。
 * 进来先到店门口，点一下进门，她进来和制作人说话，点单后调酒台打开、文本框写这一单的备忘（useBarVisit、lib/barVisit、lib/barScene），
 * 照原版调好上酒（BarCounter、lib/barMixer），调酒时配方书盖住她（BarRecipeBook），她接着反应、点下一单。
 * 她告别、最后一页点过以后出结束卡（BarEndCard），「再营业」直接迎下一位；模型出错时文本框写出错的话和「再试一次」。
 * 得了抽奖时重读一次礼物状态告诉外壳，导航「玩法」上的点随之亮起（离开玩法页以后看得到）。
 * 「离开」离开这次光顾、回玩法页，浏览器返回也是（从玩法页的卡进来）。界面上哪里都不写她的口味、醉意和档位。
 * 声音（useBarSound）：`audioBase` 是存储桶里 `bar/` 的地址，部署没给就是 null，一声不出。进门响门声；
 * 句子打字时循环打字音效，她是 `bleep_high`，制作人是 `bleep_low`。
 * 点唱机（useBarJukebox）：manifest 读完以后先过选曲界面（BarJukeboxSetup，填好上次的），Ready! 到店门口；进门从第 1 首放起，
 * 一直放到离开。店里侧边菜单「点唱机」开关右上角的小播放器（BarJukeboxPlayer）。没有曲目时跳过选曲界面，「点唱机」是灰的。
 * 教程（useBarTutorial、lib/barTutorial）：这台设备上没看过时跳过选曲界面，店门口点进去是教程，不是光顾；店门口的「教程」
 * 也从头走一遍。教程和光顾各交出一个当前场景（sceneOnScreen），这里只挑一次：文本框、立绘、调酒台、配方书都照它画，
 * 调酒时文本框写这一杯的要点，「点唱机」那一格换成「跳过」。
 * 走完或跳过去选曲界面（没有曲目时回店门口），Ready! 到店门口，再进门是真的光顾。
 * 侧边菜单（票 14）：店里上排是「设置」（BarSettingsBox：两个音量、扫描线，useBarSettings 记在这台设备上）和「全屏」
 * （useBarFullscreen，进不了全屏的浏览器没有），下排是「点唱机」（或「跳过」）和「离开」；店门口只有「离开」。
 */
export function BarSubpage({ audioBase }: { audioBase: string | null }) {
  const router = useRouter();
  const { bar, failed } = useBar();
  const { account, characters, giftsRead } = useDirectory();
  const sound = useBarSound(audioBase);
  const jukebox = useBarJukebox({ userId: account?.id ?? null, audio: sound.audio, base: audioBase });
  const { settings, change: changeSettings } = useBarSettings(account?.id ?? null);
  const [isSettingsOpen, setSettingsOpen] = useState(false);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const [canSetMusic, setCanSetMusic] = useState(true);
  useEffect(() => setCanSetMusic(canSetMusicVolume()), []);
  const fullscreen = useBarFullscreen();
  const { setVolume: setSfxVolume } = sound;
  const { setVolume: setMusicVolume } = jukebox;
  useEffect(() => setSfxVolume(gainOf(settings.sfx)), [settings.sfx, setSfxVolume]);
  useEffect(() => setMusicVolume(gainOf(settings.music)), [settings.music, setMusicVolume]);
  /** The jukebox setup shown (null: as the tutorial seen says, shown once seen, skipped the first time). */
  const [choosing, setChoosing] = useState<boolean | null>(null);
  const { start: startSound, play } = sound;
  const { start: startMusic } = jukebox;
  // 进门那一下：建 AudioContext，点唱机从第 1 首放起。
  const visitSound = useMemo(
    () => ({
      start: () => {
        startSound();
        startMusic();
      },
      play,
    }),
    [startSound, startMusic, play],
  );
  const onDraws = useCallback(() => {
    getGiftState().then(giftsRead, () => {});
  }, [giftsRead]);
  const { state, current: visitScene, enter, again, leave, retry } = useBarVisit({
    userId: account?.id ?? null,
    characters,
    sound: visitSound,
    onDraws,
  });
  const onTutorialEnd = useCallback((end: TutorialEnd) => {
    if (end === "jukebox") setChoosing(true);
  }, []);
  const tutorial = useBarTutorial({
    userId: account?.id ?? null,
    characters,
    hasJukebox: jukebox.isAvailable,
    sound,
    music: jukebox,
    onEnd: onTutorialEnd,
  });
  const isTutorial = tutorial.current !== null;
  /** What the screen shows: the tutorial's scene through it, the visit's otherwise. */
  const current = tutorial.current ?? visitScene;
  const { scene, now } = current;
  // 上酒、出错是光顾的事（教程里光顾停在店门口，两样都没有）：上酒的请求在路上时调酒台锁着，出错时她不开口、不响打字音效。
  const isMixing = isCounterOpen(scene);
  const isCounterUnlocked = isMixing && !state.isServing;
  const isFailed = state.failure !== null;
  const drinks = bar?.enabled ? bar.drinks : [];
  const counter = useBarCounter({
    mixer: scene.mixer,
    // 设置框开着时调酒台的键盘不起作用（点击有框外那一层挡着）。
    isCounterOpen: isCounterUnlocked && !isSettingsOpen,
    drinks,
    sound,
    onMix: current.mix,
    serve: current.serve,
  });

  const voice = isFailed ? null : typingVoice(scene, now);
  const { loop } = sound;
  useEffect(() => {
    loop(voice && TYPING_SOUND[voice]);
  }, [voice, loop]);

  const her = characters?.find((c) => c.id === current.guest?.characterId) ?? null;
  // 她的台词也出声（酒馆语音）：她的每一句出现时向 /api/bar/tts 要一段 mp3 播放。
  useBarVoice({
    line: scene.shown?.line ?? null,
    queue: scene.queue,
    characterId: her?.id ?? null,
    enabled: true,
    say: sound.say,
    stopSay: sound.stopSay,
  });

  if (bar && !bar.enabled) notFound();
  if (!bar && !failed) return <div className="bar-layer absolute inset-0" style={{ background: BAR_INK.ground }} />;
  // manifest 还在读、或者有曲目但还不知道是谁（记着的选择按用户分开）时，先盖一层黑的，不让店门口闪一下又换成选曲界面。
  // 这台设备上看没看过教程还没读出来时也一样（第一次进来跳过选曲界面）。
  const isReading = sound.audio === null || (jukebox.isAvailable && !jukebox.jukebox) || tutorial.isSeen === null;
  const isChoosing = choosing ?? tutorial.isSeen === true;
  const isInside = isTutorial || state.stage === "visit" || state.stage === "next";
  const card = endCard(state);
  // 设置框只在店里开着：回到店门口、出结束卡时收起，「再营业」以后不再自己弹出来。
  const isSettingsShown = isSettingsOpen && isInside && !card;
  if (isSettingsOpen && !isSettingsShown) setSettingsOpen(false);
  const leaveBar = () => {
    leave();
    router.push(playHref());
  };
  return (
    <BarScreen
      room={<BarRoom />}
      guest={
        her && <BarGuest key={current.guest?.key} character={her} mood={scene.mood} speaking={!isFailed && isSpeaking(scene, now)} />
      }
      book={isMixing && <BarRecipeBook drinks={drinks} isCounterOpen={isCounterUnlocked} counter={counter} sound={sound} />}
      portrait={<PortraitGuard />}
      scanlines={settings.scanlines}
    >
      {isInside ? (
        <>
          <BarCounter mixer={scene.mixer} isCounterOpen={isCounterUnlocked} counter={counter} />
          <BarTextBox
            text={shownText(scene, now)}
            herColor={her?.color ?? BAR_INK.text}
            isArrowShown={isArrowShown(scene, now)}
            isNextCursor={scene.shown !== null && !isMixing}
            onTap={current.tap}
            memo={mixingMemo(scene)}
            failure={state.failure === null ? null : { message: state.failure, isRetrying: state.isRetrying, onRetry: retry }}
          />
        </>
      ) : (
        <BarDoor
          notice={state.notice}
          isEntering={state.stage === "entering"}
          onEnter={() => void (tutorial.isSeen === false ? tutorial.begin() : enter())}
          onTutorial={tutorial.canBegin ? () => void tutorial.begin() : null}
        />
      )}
      <SideMenu
        settings={
          isInside
            ? {
                label: copy.bar.settings.name,
                color: BAR_INK.text,
                pressed: isSettingsShown,
                onClick: () => setSettingsOpen((open) => !open),
              }
            : null
        }
        fullscreen={
          isInside && fullscreen.canFullscreen
            ? {
                label: fullscreen.isFullscreen ? copy.bar.screen.window : copy.bar.screen.full,
                color: BAR_INK.text,
                onClick: fullscreen.toggle,
              }
            : null
        }
        jukebox={
          isTutorial
            ? { label: copy.bar.skip, color: BAR_INK.text, onClick: tutorial.skip }
            : isInside
              ? jukeboxCell(!jukebox.isAvailable ? "none" : jukebox.isOpen ? "open" : "closed", () => {
                  play(jukebox.isOpen ? "buttonnoclick" : "mixdone");
                  jukebox.toggleOpen();
                })
              : null
        }
        leave={copy.bar.leave}
        onLeave={leaveBar}
      />
      {isInside && !isTutorial && jukebox.isOpen && <BarJukeboxPlayer jukebox={jukebox} sound={sound} />}
      {isSettingsShown && (
        <BarSettingsBox
          settings={settings}
          hasAudio={jukebox.isAvailable}
          canSetMusic={canSetMusic}
          sound={sound}
          onChange={changeSettings}
          onClose={closeSettings}
        />
      )}
      {card && (
        <BarEndCard
          {...card}
          herName={her && (her.short_name ?? her.name)}
          herColor={her?.color ?? BAR_INK.text}
          onAgain={again}
          onLeave={leaveBar}
        />
      )}
      {isReading ? (
        <div className="absolute inset-0" style={{ background: BAR_INK.black }} />
      ) : (
        isChoosing &&
        jukebox.isAvailable &&
        jukebox.jukebox && (
          <BarJukeboxSetup
            tracks={sound.audio?.tracks ?? []}
            slots={jukebox.jukebox.slots}
            jukebox={jukebox}
            sound={sound}
            onReady={(slots) => {
              jukebox.choose(slots);
              setChoosing(false);
            }}
          />
        )
      )}
    </BarScreen>
  );
}
