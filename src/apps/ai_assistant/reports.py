from apps.public.reports import SEVERITY_LABELS, URGENCY_PRIORITY, item_text, make_section, min_health_score


def build_leaf_report(analysis):
    findings = (
        [f'بیماری: {d}' for d in analysis.diseases or []]
        + [f'کمبود: {d}' for d in analysis.deficiencies or []]
        + [f'آفت: {d}' for d in analysis.pests or []]
    )
    warnings = []
    if analysis.urgency:
        warnings.append(f'فوریت اقدام: {SEVERITY_LABELS.get(analysis.urgency.lower(), analysis.urgency)}')
    if analysis.treatment_time:
        warnings.append(f'زمان مناسب درمان: {analysis.treatment_time}')
    sections = [
        make_section('findings', findings),
        make_section('warnings', warnings),
        make_section('recommendations', analysis.recommendations),
        make_section('prevention', analysis.prevention),
    ]
    urgency = (analysis.urgency or '').lower()
    priority = URGENCY_PRIORITY.get(urgency)
    if priority is None:
        score = analysis.health_score
        threshold = min_health_score()
        priority = 'high' if score is not None and score < threshold else (
            'medium' if findings or (score is not None and score < threshold + 20) else 'low')
    return sections, priority


def experiment_group(result, key, label):
    group = result.get(key) or {}
    if not isinstance(group, dict):
        return [], []
    findings = [f'{label}: {group["status"]}'] if group.get('status') else []
    findings.extend(f'{label} - {f}' for f in group.get('findings') or [])
    issues = [f'{label} - {i}' for i in group.get('issues') or []]
    return findings, issues


def build_experiment_report(result):
    findings, issues = [], []
    for key, label in (('soil', 'خاک'), ('leaf', 'برگ'), ('water', 'آب')):
        group_findings, group_issues = experiment_group(result, key, label)
        findings.extend(group_findings)
        issues.extend(group_issues)
    recommendations = []
    recommendations.extend(f'آبیاری: {i}' for i in result.get('irrigation') or [])
    for item in result.get('fertilization') or []:
        recommendations.append(f'کوددهی: {item_text(item)}')
    for item in result.get('spraying') or []:
        recommendations.append(f'سم‌پاشی: {item_text(item)}')
    recommendations.extend(f'اصلاح‌کننده: {a}' for a in result.get('amendments') or [])
    sections = [
        make_section('findings', findings),
        make_section('warnings', issues + list(result.get('warnings') or []), title='مشکلات و هشدارها'),
        make_section('recommendations', recommendations),
        make_section('prevention', result.get('follow_up'), title='پیگیری و اقدامات بعدی'),
    ]
    priority = URGENCY_PRIORITY.get(result.get('urgency'), 'medium')
    return sections, priority
