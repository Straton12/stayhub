    # ---- Init ------------------------------------------------------------
def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ----------------------------------------------
        #  Publish-to-marketplace checkbox default
        # ----------------------------------------------
        #   • New property   → checked
        #   • Editing        → reflects the linked listing's live status
        if self.instance and self.instance.pk:
            listing = getattr(self.instance, 'listing', None)
            if listing is not None:
                self.fields['publish_to_marketplace'].initial = (
                    listing.status == 'approved' and listing.is_active
                )
            else:
                # Property exists but was never published
                self.fields['publish_to_marketplace'].initial = False
        else:
            self.fields['publish_to_marketplace'].initial = True

        # ----------------------------------------------
        #  Restrict the category dropdown to BnB categories
        # ----------------------------------------------
        try:
            from marketplace.models import ListingCategory
            from django.db.models import Q

            # Start with the whitelist
            allowed_slugs = list(BNB_ALLOWED_CATEGORY_SLUGS)

            # If we're editing, ALWAYS include the property's current category,
            # even if it isn't in the whitelist — so old data can't be silently
            # stripped when the form is saved.
            current_cat_id = None
            if self.instance and self.instance.pk and self.instance.category_id:
                current_cat_id = self.instance.category_id
                current_slug = getattr(self.instance.category, 'slug', None)
                if current_slug and current_slug not in allowed_slugs:
                    allowed_slugs.append(current_slug)

            # Seed the `stays` row if the whitelist references it but it's missing
            if 'stays' in allowed_slugs:
                ListingCategory.objects.get_or_create(
                    slug='stays',
                    defaults={
                        'name': 'Stays',
                        'icon': 'bed',
                        'accent': 'indigo',
                        'display_order': 10,
                    },
                )

            # Assign the filtered queryset
            base_qs = (
                ListingCategory.objects
                .filter(slug__in=allowed_slugs)
                .order_by('display_order', 'name')
            )

            # If editing and the current category isn't in the filtered set,
            # pull it back in so the dropdown doesn't lose the selection.
            if current_cat_id and not base_qs.filter(pk=current_cat_id).exists():
                extra = ListingCategory.objects.filter(pk=current_cat_id).first()
                if extra:
                    base_qs = (
                        ListingCategory.objects
                        .filter(Q(pk=current_cat_id) | Q(slug__in=allowed_slugs))
                        .order_by('display_order', 'name')
                    )

            self.fields['category'].queryset = base_qs
            self.fields['category'].empty_label = '— Choose a category —'
            self.fields['category'].help_text = ''

        except Exception:
            # Never break the whole form because of a category-lookup bug.
            # Worst case: dropdown shows whatever the model's default
            # queryset would produce.
            pass

        # ----------------------------------------------
        #  Amenities — populate the picker from the org's library
        # ----------------------------------------------
        try:
            org = None

            # Determine the org to filter by:
            #   • Editing → the property's org
            #   • Creating → whatever the view attached to form.instance
            if self.instance and self.instance.pk and self.instance.organization_id:
                org = self.instance.organization
            else:
                org = getattr(self.instance, 'organization', None)

            if org is not None:
                self.fields['amenities_picker'].queryset = (
                    Amenity.objects
                    .filter(organization=org, is_active=True)
                    .order_by('category', 'display_order', 'name')
                )
            else:
                self.fields['amenities_picker'].queryset = Amenity.objects.none()

            # Placeholder for the empty "add" option
            self.fields['amenities_picker'].empty_label = '— Add an amenity —'

            # Pre-fill the hidden field with the current names (edit mode)
            if self.instance and self.instance.pk:
                current_names = [
                    a.strip()
                    for a in (self.instance.amenities or '').splitlines()
                    if a.strip()
                ]
                self.fields['amenities_value'].initial = '\n'.join(current_names)

        except Exception:
            # Never break the form because of an amenities-lookup bug.
            pass