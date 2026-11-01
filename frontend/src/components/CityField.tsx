"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxSelectTrigger,
} from "@/components/ui/combobox";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { copy } from "@/i18n";
import { nearestCity, searchCities, type City } from "@/lib/api";
import { cityLabel, sameCity } from "@/lib/producerProfile";

const t = copy.settings.profile;

/** 找城市失败时说给用户的原因：后端答的那句话。 */
function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** 输入停下这么久才去搜，免得每敲一个字都问一次和风天气。 */
const SEARCH_DELAY_MS = 350;

/** 制作人档案里的「所在城市」（GLOSSARY.md「制作人档案」）：按名字搜，或者用浏览器给的位置找最近的城市，
 * 都经后端问部署者的和风天气；位置只用来找城市，不存。部署者没配和风天气时整项不显示（调用处不渲染）。 */
export function CityField({
  id,
  city,
  onChange,
}: {
  id: string;
  city: City | null;
  onChange: (city: City | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<City[]>([]);
  const [searching, setSearching] = useState(false);
  const [locating, setLocating] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const name = query.trim();
    if (!name || (city && name === cityLabel(city))) {
      setFound([]);
      setSearching(false);
      return;
    }
    let current = true;
    setSearching(true);
    const timer = setTimeout(() => {
      searchCities(name).then(
        (cities) => current && setFound(cities),
        (e: unknown) => current && setProblem(messageOf(e)),
      ).finally(() => current && setSearching(false));
    }, SEARCH_DELAY_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [query, city]);

  // 选中的城市留在选项里，新的搜索结果出来时它照样显示得出。
  const items = useMemo(
    () => (city && !found.some((c) => sameCity(c, city)) ? [city, ...found] : found),
    [city, found],
  );

  function locate() {
    setProblem(null);
    if (!("geolocation" in navigator)) {
      setProblem(t.cityNoPosition);
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        nearestCity(position.coords.latitude, position.coords.longitude).then(
          (nearest) => (nearest ? onChange(nearest) : setProblem(t.cityNone)),
          (e: unknown) => setProblem(messageOf(e)),
        ).finally(() => setLocating(false));
      },
      () => {
        setProblem(t.cityNoPosition);
        setLocating(false);
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 },
    );
  }

  return (
    <Field data-invalid={problem ? true : undefined}>
      <FieldLabel htmlFor={id}>{t.city}</FieldLabel>
      <div className="flex flex-wrap gap-2">
        <Combobox
          items={items}
          filter={null}
          value={city}
          onValueChange={(value: City | null) => {
            setProblem(null);
            onChange(value);
          }}
          itemToStringLabel={cityLabel}
          isItemEqualToValue={(a: City, b: City) => sameCity(a, b)}
          inputValue={query}
          onInputValueChange={setQuery}
        >
          <ComboboxSelectTrigger id={id} className="min-w-0 flex-1" placeholder={t.cityUnset} />
          <ComboboxContent>
            <ComboboxInput showTrigger={false} placeholder={t.citySearch} />
            <ComboboxEmpty>{searching ? t.citySearching : query.trim() ? t.cityNone : null}</ComboboxEmpty>
            <ComboboxList>
              {(item: City) => (
                <ComboboxItem key={`${item.name}-${item.latitude}-${item.longitude}`} value={item}>
                  {cityLabel(item)}
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
        <Button type="button" variant="outline" onClick={locate} disabled={locating}>
          {locating && <Spinner data-icon="inline-start" />}
          {t.cityHere}
        </Button>
        {city && (
          <Button type="button" variant="ghost" onClick={() => onChange(null)}>
            {t.cityClear}
          </Button>
        )}
      </div>
      {problem && <FieldError>{problem}</FieldError>}
    </Field>
  );
}
