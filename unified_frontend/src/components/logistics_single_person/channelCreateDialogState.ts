export type ChannelCreateDialogState = {
  open: boolean
  name: string
  department: string
  error: string
  submitting: boolean
}

export type ChannelCreateDialogAction =
  | { type: 'open' }
  | { type: 'close' }
  | { type: 'change-name'; name: string }
  | { type: 'change-department'; department: string }
  | { type: 'submit' }
  | { type: 'success' }
  | { type: 'failure'; error: string }

export const initialChannelCreateDialogState: ChannelCreateDialogState = {
  open: false,
  name: '',
  department: '',
  error: '',
  submitting: false,
}

export function channelCreateDialogReducer(
  state: ChannelCreateDialogState,
  action: ChannelCreateDialogAction,
): ChannelCreateDialogState {
  switch (action.type) {
    case 'open':
      return { ...state, open: true, error: '' }
    case 'close':
      return initialChannelCreateDialogState
    case 'change-name':
      return { ...state, name: action.name, error: '' }
    case 'change-department':
      return { ...state, department: action.department, error: '' }
    case 'submit':
      return { ...state, error: '', submitting: true }
    case 'success':
      return initialChannelCreateDialogState
    case 'failure':
      return { ...state, error: action.error, submitting: false }
  }
}
