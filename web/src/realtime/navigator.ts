type NavigateFn = (path: string) => void;

let navigate: NavigateFn | null = null;

export function registerNavigate(fn: NavigateFn | null) {
  navigate = fn;
}

export function appNavigate(path: string) {
  if (navigate) navigate(path);
  else window.location.assign(path);
}
