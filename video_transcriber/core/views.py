from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from .forms import UploadForm
from .models import Upload, Output
from .tasks import process_media_from_url, process_media_from_file


@login_required
def upload_view(request):
    form = UploadForm()

    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES)
        
        if form.is_valid():
            file_url = form.cleaned_data.get('file_url')
            uploaded_file = form.cleaned_data.get('file')
            output_types = list(form.cleaned_data.get('output_types', []))

            existing = None

            if file_url:
                existing = Upload.objects.filter(
                    file_url=file_url,
                    user=request.user
                ).first()
            elif uploaded_file:
                existing = Upload.objects.filter(
                    file__endswith=uploaded_file.name,
                    user=request.user
                ).first()

            if existing:
                upload = existing
            else:
                upload = form.save(commit=False)
                upload.user = request.user
                upload.save()

            
            if upload.file_url:
                process_media_from_url.delay(upload.id, output_types)
            elif upload.file:
                process_media_from_file.delay(upload.id, output_types)
                
            return redirect(to='dashboard')
    return render(request, template_name='core/upload.html', context={'form': form})


@login_required
def dashboard_view(request):
    uploads = Upload.objects.filter(user=request.user).order_by('-created_at')
    return render(request, template_name='core/dashboard.html', context={'uploads': uploads})


@login_required
def output_view(request, upload_id):
    upload = Upload.objects.filter(id=upload_id, user=request.user).first()

    if not upload:
        return redirect(to='dashboard')
    
    outputs = Output.objects.filter(upload=upload)
    return render(request, template_name='core/releted_files.html', context={'upload': upload, 'outputs': outputs})