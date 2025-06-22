from django.utils.text import slugify

def generate_unique_slug(instance, model_class, slug_field_name='slug'):
    base_slug = slugify(instance.name)
    slug = base_slug
    index = 1

    slug_field = model_class._meta.get_field(slug_field_name).attname

    while model_class.objects.filter(**{slug_field: slug}).exclude(pk=instance.pk).exists():
        slug = f"{base_slug}-{index}"
        index += 1

    return slug