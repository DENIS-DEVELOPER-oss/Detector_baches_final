"""Formularios del modulo de deteccion."""

from pathlib import Path

from django import forms

from apps.analisis.models import Analisis, Zona
from apps.usuarios.forms import MixinBootstrap

from .services import FabricaDetectores

TAMANO_MAXIMO_MB = 100


class DatosAnalisisMixin(MixinBootstrap):
    """Campos comunes de contexto (titulo, zona, ubicacion) para los 5 modos."""

    # El input de archivo va oculto dentro de la zona de arrastre. Con el
    # atributo `required` del navegador, Chrome se niega a enviar el formulario
    # y no puede mostrar el aviso sobre un campo invisible: el boton parece no
    # hacer nada. La obligatoriedad se valida en el servidor.
    use_required_attribute = False

    def _preparar(self):
        self.fields["zona"].queryset = Zona.objects.filter(activa=True)
        self.fields["zona"].empty_label = "Sin zona especifica"
        self.fields["zona"].required = False
        # Lo unico realmente imprescindible es el archivo; el resto es contexto.
        self.fields["titulo"].required = False
        self.fields["titulo"].widget.attrs.setdefault(
            "placeholder", "Opcional: se genera solo si lo deja vacio"
        )
        self._estilizar()


class SubirArchivoForm(DatosAnalisisMixin, forms.ModelForm):
    """Modo 1 y 2: subir una imagen o un video desde el dispositivo."""

    class Meta:
        model = Analisis
        fields = ["titulo", "descripcion", "zona", "direccion_referencia",
                  "latitud", "longitud", "archivo"]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 2}),
            "latitud": forms.NumberInput(attrs={"step": "any"}),
            "longitud": forms.NumberInput(attrs={"step": "any"}),
            "archivo": forms.ClearableFileInput(
                attrs={"accept": "image/*,video/mp4,video/webm,video/x-msvideo"}
            ),
        }
        help_texts = {
            "archivo": "Imagen (JPG, PNG, WEBP) o video (MP4, WEBM, AVI, MOV). Maximo 100 MB.",
        }
        error_messages = {
            "archivo": {"required": "Elija una imagen o un video antes de analizar."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._preparar()

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        extension = Path(archivo.name).suffix.lower()

        if extension not in FabricaDetectores.extensiones_validas():
            validas = ", ".join(sorted(FabricaDetectores.extensiones_validas()))
            raise forms.ValidationError(f"Formato no soportado. Use: {validas}")

        if archivo.size > TAMANO_MAXIMO_MB * 1024 * 1024:
            raise forms.ValidationError(f"El archivo supera los {TAMANO_MAXIMO_MB} MB.")

        return archivo


class CapturaCamaraForm(DatosAnalisisMixin, forms.ModelForm):
    """Modo 3 y 4: foto tomada o video grabado con la camara del dispositivo.

    El archivo no llega por un `<input type=file>` sino como blob generado por
    el navegador, asi que se adjunta en la vista y aqui solo se valida contexto.
    """

    class Meta:
        model = Analisis
        fields = ["titulo", "descripcion", "zona", "direccion_referencia",
                  "latitud", "longitud"]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 2}),
            "latitud": forms.NumberInput(attrs={"step": "any"}),
            "longitud": forms.NumberInput(attrs={"step": "any"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._preparar()
