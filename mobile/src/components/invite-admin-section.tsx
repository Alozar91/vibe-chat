/**
 * Админ-секция инвайтов (§12): создание multi-use кодов, список,
 * деактивация. Код показывается один раз (в БД только sha256) — §5.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { invitesApi } from "../api/endpoints";
import { t } from "../i18n/ru";
import { theme } from "../theme";

export function InviteAdminSection() {
  const queryClient = useQueryClient();
  const invites = useQuery({ queryKey: ["invites"], queryFn: invitesApi.list });

  const create = useMutation({
    mutationFn: () => invitesApi.create(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invites"] }),
  });

  const deactivate = useMutation({
    mutationFn: (id: string) => invitesApi.deactivate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invites"] }),
  });

  const created = create.data;

  return (
    <View style={styles.section}>
      <Text style={styles.title}>{t("invites.title")}</Text>
      <Pressable style={styles.createBtn} onPress={() => create.mutate()} disabled={create.isPending}>
        <Text style={styles.createBtnText}>
          {create.isPending ? t("invites.creating") : t("invites.create")}
        </Text>
      </Pressable>
      {created ? (
        <Text style={styles.codeOnce}>
          {t("invites.codeOnce", { code: created.code })}
        </Text>
      ) : null}
      {(invites.data ?? []).length === 0 && !invites.isLoading ? (
        <Text style={styles.empty}>{t("invites.empty")}</Text>
      ) : null}
      {(invites.data ?? []).map((inv) => {
        const active = inv.deactivated_at === null;
        return (
          <View key={inv.id} style={styles.row}>
            <View style={styles.rowCenter}>
              <Text style={styles.uses}>
                {t("invites.uses", {
                  count: inv.uses_count,
                  max: inv.max_uses ?? t("invites.unlimited"),
                })}
              </Text>
              {!active ? <Text style={styles.deactivated}>{t("invites.deactivated")}</Text> : null}
            </View>
            {active ? (
              <Pressable onPress={() => deactivate.mutate(inv.id)}>
                <Text style={styles.deactivateBtn}>{t("invites.deactivate")}</Text>
              </Pressable>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    padding: theme.spacing.md,
    marginTop: theme.spacing.lg,
  },
  title: { fontSize: theme.font.sm, fontWeight: "600", color: theme.colors.textSecondary },
  createBtn: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 8,
    marginTop: theme.spacing.sm,
  },
  createBtnText: { color: theme.colors.primaryText, fontSize: theme.font.sm, fontWeight: "500" },
  codeOnce: { color: theme.colors.accentGreen, fontSize: theme.font.sm, marginTop: theme.spacing.sm },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 6,
    borderTopWidth: 1,
    borderTopColor: theme.colors.border,
    marginTop: theme.spacing.sm,
  },
  rowCenter: { flex: 1 },
  uses: { fontSize: theme.font.sm, color: theme.colors.text },
  deactivated: { fontSize: theme.font.sm, color: theme.colors.textSecondary },
  deactivateBtn: { color: theme.colors.danger, fontSize: theme.font.sm },
  empty: { color: theme.colors.textSecondary, fontSize: theme.font.sm, marginTop: theme.spacing.sm },
});
