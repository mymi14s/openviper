import type { ModelField } from '@/types/admin'

/** Map of Django field type names to HTML input types. */
const FIELD_TYPE_MAP: Record<string, string> = {
  text: 'text',
  string: 'text',
  email: 'email',
  url: 'url',
  number: 'number',
  password: 'password',
  date: 'date',
  datetime: 'datetime-local',
  time: 'time',
  boolean: 'checkbox',
  textarea: 'textarea',
  select: 'select',
  file: 'file',
  image: 'file',
  CharField: 'text',
  SlugField: 'text',
  IPAddressField: 'text',
  EmailField: 'email',
  URLField: 'url',
  IntegerField: 'number',
  BigIntegerField: 'number',
  PositiveIntegerField: 'number',
  AutoField: 'number',
  FloatField: 'number',
  DecimalField: 'number',
  PasswordField: 'password',
  DateField: 'date',
  DateTimeField: 'datetime-local',
  TimeField: 'time',
  BooleanField: 'checkbox',
  TextField: 'textarea',
  JSONField: 'textarea',
  UUIDField: 'text',
  ForeignKey: 'select',
  OneToOneField: 'select',
  ManyToManyField: 'select',
  FileField: 'file',
  ImageField: 'file',
  PointField: 'point',
}

/** Resolve a ModelField to its HTML input type. */
export function getFieldType(field: ModelField): string {
  return FIELD_TYPE_MAP[field.type] || 'text'
}

/** Resolve a ModelField to the component kind used to render it. */
export function getFieldComponent(field: ModelField): string {
  if (field.type === 'FileField' || field.type === 'ImageField' ||
      field.component === 'file' || field.component === 'image') {
    return 'file'
  }
  if (field.type === 'CountryField' || field.component === 'country') {
    return 'country'
  }
  if (field.type === 'PointField' || field.component === 'point') {
    return 'point'
  }
  if (field.related_model) return 'foreignkey'
  const inputType = getFieldType(field)
  if (field.choices && field.choices.length > 0) return 'select'
  if (inputType === 'checkbox') return 'checkbox'
  if (inputType === 'textarea') return 'textarea'
  if (inputType === 'select') return 'select'
  return 'input'
}

/** Build HTML input attributes from a ModelField definition. */
export function getInputAttributes(field: ModelField): Record<string, string | number | boolean> {
  const attrs: Record<string, string | number | boolean> = {}
  const fieldType = getFieldType(field)

  if (field.max_length) {
    attrs.maxlength = field.max_length
  }

  if (fieldType === 'number') {
    if (field.min_value !== undefined && field.min_value !== null) {
      attrs.min = field.min_value
    }
    if (field.max_value !== undefined && field.max_value !== null) {
      attrs.max = field.max_value
    }
    attrs.step = (field.type === 'FloatField' || field.type === 'DecimalField') ? '0.01' : '1'
  }

  if (field.type === 'IPAddressField') {
    attrs.pattern = '^(\\d{1,3}\\.){3}\\d{1,3}$'
    attrs.placeholder = 'e.g., 192.168.1.1'
  } else if (field.type === 'SlugField') {
    attrs.pattern = '^[a-z0-9]+(?:-[a-z0-9]+)*$'
    attrs.placeholder = 'lowercase-with-hyphens'
  } else if (field.type === 'UUIDField') {
    attrs.pattern = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    attrs.readonly = true
  }

  return attrs
}
