// content script の document 束縛 injector。
//
// entrypoint から切り離し、DOM fixture を使う unit/integration test で
// 実配線（profile.artist -> Apple Music credits など）を直接検証できるようにする。

import {
  acceptImportantTerms,
  assertNewRelease,
  checkAllStores,
  injectAiDisclosure,
  injectAlbumTitle,
  injectAppleMusicCredits,
  injectCover,
  injectProfile,
  injectReleaseDate,
  injectSongwriter,
  injectTrackFile,
  injectTrackTitle,
  RELOAD_GUIDANCE,
  resolveTrackUuids,
  scrollToDoneButton,
  setTrackCount,
  uncheckUpsells,
} from "./distrokid-injector";
import type { Injector } from "./inject-session";
import type { ReleasePayload } from "./types";

export function createDocumentInjector(doc: Document): Injector {
  return {
    async injectStaticFields(payload: ReleasePayload): Promise<void> {
      const { profile, release } = payload;
      // (B) トラック数を payload に合わせて set し、track 行の生成完了を待つ（#888）。
      // 以降の注入（assert / プロファイル / タイトル / credit）は行生成後に開始する（順序保証）。
      await setTrackCount(doc, release.tracks.length);

      // 新規リリース前提を assert（過去公開対応はスコープ外）。
      assertNewRelease(doc);
      await injectProfile(doc, profile);
      injectAlbumTitle(doc, release.album_title);
      injectReleaseDate(doc, release.release_date);

      // track UUID を DOM order で解決し、全 track のタイトル / songwriter を注入する。
      const uuids = resolveTrackUuids(doc);
      if (uuids.length !== release.tracks.length) {
        throw new Error(
          `track 数が DOM と一致しません: DOM=${uuids.length}, payload=${release.tracks.length}。${RELOAD_GUIDANCE}`,
        );
      }
      release.tracks.forEach((track, i) => {
        injectTrackTitle(doc, uuids[i], track.title);
        if (profile.songwriter !== null) {
          injectSongwriter(doc, i + 1, profile.songwriter);
        }
      });

      // Apple Music check が credits 可視化の前提になるため、ストア check を先に行う（#923）。
      checkAllStores(doc);
      // chk* 除外済みなので配信先は巻き込まない（#923）。
      uncheckUpsells(doc);
      // ストア check 後に可視化されるため await（#923）。
      await injectAppleMusicCredits(doc, release.tracks.length, profile.artist, profile.credits);
      // ストア check 後でないと条件付き areyousure が不可視のため、ストア check 後に実行（#923）。
      acceptImportantTerms(doc);
    },
    injectTrackFile(trackIndex: number, file: File): void {
      // injector は 0-indexed、DOM の file input は 1-indexed。
      injectTrackFile(doc, trackIndex + 1, file);
    },
    injectCover(file: File): void {
      injectCover(doc, file);
    },
    async injectAiDisclosure(payload: ReleasePayload): Promise<void> {
      await injectAiDisclosure(doc, payload.profile.ai_disclosure);
      // (E) フィル完了直後、続けるボタンを視界へスクロール（#919）。送信は人間が手動で押す。
      scrollToDoneButton(doc);
    },
  };
}
