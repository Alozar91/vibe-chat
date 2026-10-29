import { useQuery } from "@tanstack/react-query";
import { authApi, meApi, usersApi } from "../../api/endpoints";
import type { User } from "../../api/types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => meApi.get(),
    retry: false,
    staleTime: 60_000,
  });
}

export function useUser(userId: string | null | undefined) {
  return useQuery({
    queryKey: ["user", userId],
    queryFn: () => usersApi.get(userId as string),
    enabled: !!userId,
    staleTime: 10 * 60_000,
  });
}

export function useSessions() {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: () => authApi.sessions(),
  });
}

export function isAdmin(me: User | undefined | null): boolean {
  return me?.role === "owner" || me?.role === "admin";
}
