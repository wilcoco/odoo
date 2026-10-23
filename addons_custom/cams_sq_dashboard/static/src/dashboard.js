/** @odoo-module **/
import { Component, onWillStart, useState } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';

export class SqDashboard extends Component {
    static template = 'cams_sq_dashboard.Dashboard';
    setup() {
        this.orm = useService('orm'); this.action = useService('action');
        this.state = useState({ data: null, start: '', end: '', busy: false });
        onWillStart(() => this.refresh());
    }
    async refresh() {
        this.state.busy = true;
        try {
            this.state.data = await this.orm.call('iatf.sq.dashboard', 'get_dashboard_data', [], {
                date_from: this.state.start || null, date_to: this.state.end || null });
            this.state.start = this.state.data.date_from; this.state.end = this.state.data.date_to;
        } finally { this.state.busy = false; }
    }
    async openBoard(board) {
        const action = await this.orm.call('iatf.sq.dashboard', 'open_records', [board.model, this.state.start, this.state.end]);
        return this.action.doAction(action);
    }
    async openReceipts() {
        const action = await this.orm.call('iatf.sq.dashboard', 'open_receipt_coverage', [this.state.start, this.state.end]);
        return this.action.doAction(action);
    }
}
registry.category('actions').add('cams_sq_dashboard.Dashboard', SqDashboard);
