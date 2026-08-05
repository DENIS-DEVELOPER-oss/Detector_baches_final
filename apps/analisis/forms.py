"""Formularios de consulta y georreferenciacion de los analisis realizados."""

from django import forms

from apps.usuarios.forms import MixinBootstrap

from .models import Analisis, Ciudad, NivelSeveridad, TipoOrigen, Zona


class UbicacionForm(MixinBootstrap, forms.ModelForm):
    """Situa un analisis ya guardado en el mapa.

    Permite georreferenciar despues del hecho: una foto subida sin coordenadas
    no aparece en el mapa, y sin este formulario no habria forma de arreglarlo.
    """

    class Meta:
        model = Analisis
        fields = ["zona", "direccion_referencia", "latitud", "longitud"]
        widgets = {
            "latitud": forms.NumberInput(attrs={"step": "any"}),
            "longitud": forms.NumberInput(attrs={"step": "any"}),
            "direccion_referencia": forms.TextInput(
                attrs={"placeholder": "Ej. frente al mercado Tupac Amaru"}
            ),
        }
        labels = {"direccion_referencia": "Direccion o referencia"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["zona"].queryset = Zona.objects.filter(activa=True)
        self.fields["zona"].empty_label = "Sin zona especifica"
        self.fields["zona"].required = False
        self._estilizar()

    def clean(self):
        datos = super().clean()
        latitud, longitud = datos.get("latitud"), datos.get("longitud")

        # O van las dos coordenadas, o ninguna: media coordenada no ubica nada.
        if (latitud is None) != (longitud is None):
            raise forms.ValidationError(
                "Indique latitud y longitud, o marque el punto en el mapa."
            )
        if latitud is None and not datos.get("zona"):
            raise forms.ValidationError(
                "Marque un punto en el mapa o elija una zona para ubicar el analisis."
            )
        return datos


class FiltroAnalisisForm(MixinBootstrap, forms.Form):
    """Filtros del historial, del mapa y de las estadisticas."""

    q = forms.CharField(
        label="Buscar", required=False,
        widget=forms.TextInput(attrs={"placeholder": "Codigo, titulo o referencia"}),
    )
    severidad = forms.ChoiceField(
        label="Severidad", required=False,
        choices=[("", "Todas")] + list(NivelSeveridad.choices),
    )
    origen = forms.ChoiceField(
        label="Origen", required=False,
        choices=[("", "Todos")] + list(TipoOrigen.choices),
    )
    ciudad = forms.ChoiceField(
        label="Ciudad", required=False,
        choices=[("", "Todas")] + list(Ciudad.choices),
    )
    zona = forms.ModelChoiceField(
        label="Zona", required=False,
        queryset=Zona.objects.filter(activa=True), empty_label="Todas",
    )
    solo_con_danos = forms.BooleanField(label="Solo con danos", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estilizar()

    def aplicar(self, queryset):
        """Aplica los filtros validados sobre el queryset recibido."""
        if not self.is_valid():
            return queryset
        datos = self.cleaned_data

        if datos.get("q"):
            from django.db.models import Q

            texto = datos["q"]
            queryset = queryset.filter(
                Q(codigo__icontains=texto)
                | Q(titulo__icontains=texto)
                | Q(direccion_referencia__icontains=texto)
            )
        if datos.get("severidad"):
            queryset = queryset.filter(severidad_maxima=datos["severidad"])
        if datos.get("origen"):
            queryset = queryset.filter(origen=datos["origen"])
        if datos.get("ciudad"):
            queryset = queryset.filter(zona__ciudad=datos["ciudad"])
        if datos.get("zona"):
            queryset = queryset.filter(zona=datos["zona"])
        if datos.get("solo_con_danos"):
            queryset = queryset.filter(total_detecciones__gt=0)
        return queryset
